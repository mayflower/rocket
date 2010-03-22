# -*- coding: utf-8 -*-

# This file is part of the Rocket Web Server
# Copyright (c) 2009 Timothy Farrell

# Import System Modules
import os
import sys
import socket
import traceback
from email.utils import formatdate
from wsgiref.headers import Headers
from wsgiref.util import FileWrapper
# Import Package Modules
from .. import HTTP_SERVER_SOFTWARE, SERVER_NAME, b, u, BUF_SIZE, PY3K
from ..worker import Worker, ChunkedReader

# Define Constants
NEWLINE = b('\r\n')
HEADER_RESPONSE = '''HTTP/1.1 %s\r\n%s'''
BASE_ENV = {'SERVER_NAME': SERVER_NAME,
            'wsgi.errors': sys.stderr,
            'wsgi.version': (1, 0),
            'wsgi.multiprocess': False,
            'wsgi.run_once': False,
            'wsgi.file_wrapper': FileWrapper
            }

class WSGIWorker(Worker):
    def __init__(self):
        """Builds some instance variables that will last the life of the
        thread."""
        if isinstance(self.app_info, dict):
            multithreaded = self.app_info.get('max_threads') != 1
        else:
            multithreaded = False
        self.base_environ = dict({'SERVER_SOFTWARE': self.server_software,
                                  'wsgi.multithread': multithreaded,
                                  })
        self.base_environ.update(BASE_ENV)
        # Grab our application
        self.app = self.app_info['wsgi_app']

        Worker.__init__(self)

    def build_environ(self, sock_file, conn):
        """ Build the execution environment. """
        # Grab the request line
        request = self.read_request_line(sock_file)

        # Grab the headers
        self.headers = dict([(str('HTTP_'+k.upper()), v) for k, v in self.read_headers(sock_file).items()])

        # Copy the Base Environment
        environ = dict(self.base_environ)

        # Add CGI Variables
        environ['REQUEST_METHOD'] = request['method']
        environ['PATH_INFO'] = request['path']
        environ['SERVER_PROTOCOL'] = request['protocol']
        environ['SCRIPT_NAME'] = '' # Direct call WSGI does not need a name
        environ['SERVER_PORT'] = str(conn.server_port)
        environ['REMOTE_PORT'] = str(conn.client_port)
        environ['REMOTE_ADDR'] = str(conn.client_addr)
        environ['QUERY_STRING'] = request['query_string']
        if 'HTTP_CONTENT_LENGTH' in self.headers:
            environ['CONTENT_LENGTH'] = self.headers['HTTP_CONTENT_LENGTH']
        if 'HTTP_CONTENT_TYPE' in self.headers:
            environ['CONTENT_TYPE'] = self.headers['HTTP_CONTENT_TYPE']

        # Save the request method for later
        self.request_method = environ['REQUEST_METHOD'].upper()

        # Add Dynamic WSGI Variables
        if conn.ssl:
            environ['wsgi.url_scheme'] = 'https'
            environ['HTTPS'] = 'on'
        else:
            environ['wsgi.url_scheme'] = 'http'
        if self.headers.get('HTTP_TRANSFER_ENCODING', '').lower() == 'chunked':
            environ['wsgi.input'] = ChunkedReader(sock_file)
        else:
            environ['wsgi.input'] = sock_file

        # Add HTTP Headers
        environ.update(self.headers)

        return environ

    def send_headers(self, data, sections):
        h_set = self.header_set
        # Does the app want us to send output chunked?
        self.chunked = h_set.get('transfer-encoding', '').lower() == 'chunked'

        # Add a Date header if it's not there already
        if not 'date' in h_set:
            h_set['Date'] = formatdate(usegmt=True)

        # Add a Server header if it's not there already
        if not 'server' in h_set:
            h_set['Server'] = HTTP_SERVER_SOFTWARE

        if 'content-length' in h_set:
            self.size = int(h_set['content-length'])
        else:
            s = int(self.status.split(' ')[0])
            if s < 200 or s not in (204, 205, 304):
                if not self.chunked:
                    if sections == 1:
                        # Add a Content-Length header if it's not there already
                        h_set['Content-Length'] = str(len(data))
                        self.size = len(data)
                    else:
                        # If they sent us more than one section, we blow chunks
                        h_set['Transfer-Encoding'] = 'Chunked'
                        self.chunked = True
                        self.err_log.debug('Adding header...Transfer-Encoding: '
                                           'Chunked')

        if 'connection' not in h_set:
            # If the application did not provide a connection header, fill it in
            client_conn = self.headers.get('HTTP_CONNECTION', '').lower()
            if self.environ['SERVER_PROTOCOL'] == 'HTTP/1.1':
                # HTTP = 1.1 defaults to keep-alive connections
                h_set['Connection'] = client_conn if client_conn else 'keep-alive'
            else:
                # HTTP < 1.1 supports keep-alive but it's quirky so we don't support it
                h_set['Connection'] = 'close'
        
        # Close our connection if we need to.
        self.closeConnection = h_set.get('connection', '').lower() == 'close'

        # Build our output headers
        header_data = HEADER_RESPONSE % (self.status, str(h_set))

        # Send the headers
        self.err_log.debug('Sending Headers: %s' % repr(header_data))
        self.conn.sendall(b(header_data))
        self.headers_sent = True

    def write_warning(self, data, sections=None):
        self.err_log.warning('WSGI app called write method directly.  This is '
                             'deprecated behavior.  Please update your app.')
        return self.write(data, sections)

    def write(self, data, sections=None):
        """ Write the data to the output socket. """

        if self.error[0]:
            self.status = self.error[0]
            data = b(self.error[1])

        if not self.headers_sent:
            self.send_headers(data, sections)

        if self.request_method != 'HEAD':
            try:
                if self.chunked:
                    self.conn.sendall(b('%x\r\n' % len(data)))
                # Send another NEWLINE for good measure
                self.conn.sendall(data)
                if self.chunked:
                    self.conn.sendall(b('\r\n'))
            except socket.error:
                # But some clients will close the connection before that
                # resulting in a socket error.
                self.closeConnection = True

    def start_response(self, status, response_headers, exc_info=None):
        """ Store the HTTP status and headers to be sent when self.write is
        called. """
        if exc_info:
            try:
                if self.headers_sent:
                    # Re-raise original exception if headers sent
                    # because this violates WSGI specification.
                    raise
            finally:
                exc_info = None
        elif self.header_set:
            raise AssertionError("Headers already set!")

        if PY3K and not isinstance(status, str):
            self.status = str(status, 'ISO-8859-1')
        else:
            self.status = status
        # Make sure headers are bytes objects
        try:
            self.header_set = Headers(response_headers)
        except UnicodeDecodeError:
            self.error = ('500 Internal Server Error',
                          'HTTP Headers should be bytes')
            self.err_log.error('Received HTTP Headers from client that contain'
                               ' invalid characters for Latin-1 encoding.')

        return self.write_warning

    def run_app(self, conn):
        self.size = 0
        self.header_set = Headers([])
        self.headers_sent = False
        self.error = (None, None)
        self.chunked = False
        sections = None
        output = None

        self.err_log.debug('Getting sock_file')
        # Build our file-like object
        sock_file = conn.makefile('rb',BUF_SIZE)

        try:
            # Read the headers and build our WSGI environment
            self.environ = environ = self.build_environ(sock_file, conn)

            # Handle 100 Continue
            if environ.get('HTTP_EXPECT', '').lower() == '100-continue':
                res = environ['SERVER_PROTOCOL'] + ' 100 Continue\r\n\r\n'
                conn.sendall(b(res))

            # Send it to our WSGI application
            output = self.app(environ, self.start_response)
            if not hasattr(output, '__len__') and not hasattr(output, '__iter__'):
                self.error = ('500 Internal Server Error',
                              'WSGI applications must return a list or '
                              'generator type.')

            if hasattr(output, '__len__'):
                sections = len(output)

            for data in output:
                # Don't send headers until body appears
                if data:
                    self.write(data, sections)

            if self.chunked:
                # If chunked, send our final chunk length
                self.conn.sendall(b('0\r\n\r\n'))
            elif not self.headers_sent:
                # Send headers if the body was empty
                self.send_headers('', sections)

        # Don't capture exceptions here.  The Worker class handles
        # them appropriately.
        finally:
            self.err_log.debug('Finally closing output and sock_file')
            if hasattr(output,'close'):
                output.close()

            sock_file.close()
