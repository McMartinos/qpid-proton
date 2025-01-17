#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

import re
import subprocess
import time
import unittest


class Popen(subprocess.Popen):

    # We always use these options
    def __init__(self, args, **kwargs):
        super(Popen, self).\
            __init__(args,
                     shell=False,
                     stderr=subprocess.STDOUT,
                     stdout=subprocess.PIPE,
                     universal_newlines=True, **kwargs)


# Like subprocess.run with our defaults but returning the Popen object
def run(args, **kwargs):
    p = Popen(args, **kwargs)
    p.wait()
    return p

class ExamplesTest(unittest.TestCase):
    def test_helloworld(self, example="helloworld.py"):
        with run([example]) as p:
            output = [l.strip() for l in p.stdout]
            self.assertEqual(output, ['Hello World!'])

    def test_helloworld_direct(self):
        self.test_helloworld('helloworld_direct.py')

    def test_helloworld_blocking(self):
        self.test_helloworld('helloworld_blocking.py')

    def test_helloworld_tornado(self):
        self.test_helloworld('helloworld_tornado.py')

    def test_helloworld_direct_tornado(self):
        self.test_helloworld('helloworld_direct_tornado.py')

    def test_simple_send_recv(self, recv='simple_recv.py', send='simple_send.py'):
        with Popen([recv]) as r:
            with run([send]):
                pass
            actual = [l.strip() for l in r.stdout]
            expected = ["{'sequence': %i}" % (i + 1,) for i in range(100)]
            self.assertEqual(actual, expected)

    def test_client_server(self, client=['client.py'], server=['server.py'], sleep=0):
        with Popen(server) as s:
            if sleep:
                time.sleep(sleep)
            with run(client) as c:
                actual = [l.strip() for l in c.stdout]
                inputs = ["Twas brillig, and the slithy toves",
                          "Did gire and gymble in the wabe.",
                          "All mimsy were the borogroves,",
                          "And the mome raths outgrabe."]
                expected = ["%s => %s" % (l, l.upper()) for l in inputs]
                self.assertEqual(actual, expected)
            s.terminate()

    def test_sync_client_server(self):
        self.test_client_server(client=['sync_client.py'])

    def test_client_server_tx(self):
        self.test_client_server(server=['server_tx.py'])

    def test_sync_client_server_tx(self):
        self.test_client_server(client=['sync_client.py'], server=['server_tx.py'])

    def test_client_server_direct(self):
        self.test_client_server(client=['client.py', '-a', 'localhost:8888/examples'],
                                server=['server_direct.py'], sleep=0.5)

    def test_sync_client_server_direct(self):
        self.test_client_server(client=['sync_client.py', '-a', 'localhost:8888/examples'],
                                server=['server_direct.py'], sleep=0.5)

    def test_db_send_recv(self):
        self.maxDiff = None
        # setup databases
        subprocess.check_call(['db_ctrl.py', 'init', './src_db'])
        subprocess.check_call(['db_ctrl.py', 'init', './dst_db'])
        with Popen(['db_ctrl.py', 'insert', './src_db'], stdin=subprocess.PIPE) as fill:
            for i in range(100):
                fill.stdin.write("Message-%i\n" % (i + 1))
            fill.stdin.close()

        # run send and recv
        with Popen(['db_recv.py', '-m', '100']) as r:
            with run(['db_send.py', '-m', '100']):
                pass
            r.wait()
            # verify output of receive
            actual = [l.strip() for l in r.stdout]
            expected = ["inserted message %i" % (i + 1) for i in range(100)]
            self.assertEqual(actual, expected)

        # verify state of databases
        with run(['db_ctrl.py', 'list', './dst_db']) as v:
            expected = ["(%i, 'Message-%i')" % (i + 1, i + 1) for i in range(100)]
            actual = [l.strip() for l in v.stdout]
            self.assertEqual(actual, expected)

    def test_tx_send_tx_recv(self):
        self.test_simple_send_recv(recv='tx_recv.py', send='tx_send.py')

    def test_simple_send_direct_recv(self):
        self.maxDiff = None
        with Popen(['direct_recv.py', '-a', 'localhost:8888']) as r:
            time.sleep(0.5)
            with run(['simple_send.py', '-a', 'localhost:8888']):
                pass
            r.wait()
            actual = [l.strip() for l in r.stdout]
            expected = ["{'sequence': %i}" % (i + 1,) for i in range(100)]
            self.assertEqual(actual, expected)

    def test_direct_send_simple_recv(self):
        with Popen(['direct_send.py', '-a', 'localhost:8888']):
            time.sleep(0.5)
            with run(['simple_recv.py', '-a', 'localhost:8888']) as r:
                actual = [l.strip() for l in r.stdout]
                expected = ["{'sequence': %i}" % (i + 1,) for i in range(100)]
                self.assertEqual(actual, expected)

    def test_selected_recv(self):
        with run(['colour_send.py']):
            pass

        with run(['selected_recv.py', '-m', '50']) as r:
            actual = [l.strip() for l in r.stdout]
            expected = ["green %i" % (i + 1) for i in range(100) if i % 2 == 0]
            self.assertEqual(actual, expected)

        with run(['simple_recv.py', '-m', '50']) as r:
            actual = [l.strip() for l in r.stdout]
            expected = ["red %i" % (i + 1) for i in range(100) if i % 2 == 1]
            self.assertEqual(actual, expected)
