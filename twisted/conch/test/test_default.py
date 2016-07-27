# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Tests for L{twisted.conch.client.default}.
"""

from __future__ import absolute_import, division

from twisted.python.reflect import requireModule

if requireModule('cryptography') and requireModule('pyasn1'):
    from twisted.conch.client.agent import SSHAgentClient
    from twisted.conch.client.default import SSHUserAuthClient
    from twisted.conch.client.options import ConchOptions
    from twisted.conch.client import default
    from twisted.conch.ssh.keys import Key
else:
    skip = "cryptography and PyASN1 required for twisted.conch.client.default."

from twisted.trial.unittest import TestCase
from twisted.python.filepath import FilePath
from twisted.conch.error import ConchError
from twisted.conch.test import keydata
from twisted.test.proto_helpers import StringTransport
from twisted.python.compat import networkString, nativeString



class SSHUserAuthClientTests(TestCase):
    """
    Tests for L{SSHUserAuthClient}.

    @type rsaPublic: L{Key}
    @ivar rsaPublic: A public RSA key.
    """

    def setUp(self):
        self.rsaPublic = Key.fromString(keydata.publicRSA_openssh)
        self.tmpdir = FilePath(self.mktemp())
        self.tmpdir.makedirs()
        self.rsaFile = self.tmpdir.child('id_rsa')
        self.rsaFile.setContent(keydata.privateRSA_openssh)
        self.tmpdir.child('id_rsa.pub').setContent(keydata.publicRSA_openssh)


    def test_signDataWithAgent(self):
        """
        When connected to an agent, L{SSHUserAuthClient} can use it to
        request signatures of particular data with a particular L{Key}.
        """
        client = SSHUserAuthClient(b"user", ConchOptions(), None)
        agent = SSHAgentClient()
        transport = StringTransport()
        agent.makeConnection(transport)
        client.keyAgent = agent
        cleartext = b"Sign here"
        client.signData(self.rsaPublic, cleartext)
        self.assertEqual(
            transport.value(),
            b"\x00\x00\x00\x8b\r\x00\x00\x00u" + self.rsaPublic.blob() +
            b"\x00\x00\x00\t" + cleartext +
            b"\x00\x00\x00\x00")


    def test_agentGetPublicKey(self):
        """
        L{SSHUserAuthClient} looks up public keys from the agent using the
        L{SSHAgentClient} class.  That L{SSHAgentClient.getPublicKey} returns a
        L{Key} object with one of the public keys in the agent.  If no more
        keys are present, it returns L{None}.
        """
        agent = SSHAgentClient()
        agent.blobs = [self.rsaPublic.blob()]
        key = agent.getPublicKey()
        self.assertTrue(key.isPublic())
        self.assertEqual(key, self.rsaPublic)
        self.assertIsNone(agent.getPublicKey())


    def test_getPublicKeyFromFile(self):
        """
        L{SSHUserAuthClient.getPublicKey()} is able to get a public key from
        the first file described by its options' C{identitys} list, and return
        the corresponding public L{Key} object.
        """
        options = ConchOptions()
        options.identitys = [self.rsaFile.path]
        client = SSHUserAuthClient(b"user",  options, None)
        key = client.getPublicKey()
        self.assertTrue(key.isPublic())
        self.assertEqual(key, self.rsaPublic)


    def test_getPublicKeyAgentFallback(self):
        """
        If an agent is present, but doesn't return a key,
        L{SSHUserAuthClient.getPublicKey} continue with the normal key lookup.
        """
        options = ConchOptions()
        options.identitys = [self.rsaFile.path]
        agent = SSHAgentClient()
        client = SSHUserAuthClient(b"user",  options, None)
        client.keyAgent = agent
        key = client.getPublicKey()
        self.assertTrue(key.isPublic())
        self.assertEqual(key, self.rsaPublic)


    def test_getPublicKeyBadKeyError(self):
        """
        If L{keys.Key.fromFile} raises a L{keys.BadKeyError}, the
        L{SSHUserAuthClient.getPublicKey} tries again to get a public key by
        calling itself recursively.
        """
        options = ConchOptions()
        self.tmpdir.child('id_dsa.pub').setContent(keydata.publicDSA_openssh)
        dsaFile = self.tmpdir.child('id_dsa')
        dsaFile.setContent(keydata.privateDSA_openssh)
        options.identitys = [self.rsaFile.path, dsaFile.path]
        self.tmpdir.child('id_rsa.pub').setContent(b'not a key!')
        client = SSHUserAuthClient(b"user",  options, None)
        key = client.getPublicKey()
        self.assertTrue(key.isPublic())
        self.assertEqual(key, Key.fromString(keydata.publicDSA_openssh))
        self.assertEqual(client.usedFiles, [self.rsaFile.path, dsaFile.path])


    def test_getPrivateKey(self):
        """
        L{SSHUserAuthClient.getPrivateKey} will load a private key from the
        last used file populated by L{SSHUserAuthClient.getPublicKey}, and
        return a L{Deferred} which fires with the corresponding private L{Key}.
        """
        rsaPrivate = Key.fromString(keydata.privateRSA_openssh)
        options = ConchOptions()
        options.identitys = [self.rsaFile.path]
        client = SSHUserAuthClient(b"user",  options, None)
        # Populate the list of used files
        client.getPublicKey()

        def _cbGetPrivateKey(key):
            self.assertFalse(key.isPublic())
            self.assertEqual(key, rsaPrivate)

        return client.getPrivateKey().addCallback(_cbGetPrivateKey)


    def test_getPrivateKeyPassphrase(self):
        """
        L{SSHUserAuthClient} can get a private key from a file, and return a
        Deferred called back with a private L{Key} object, even if the key is
        encrypted.
        """
        rsaPrivate = Key.fromString(keydata.privateRSA_openssh)
        passphrase = b'this is the passphrase'
        self.rsaFile.setContent(rsaPrivate.toString('openssh', passphrase))
        options = ConchOptions()
        options.identitys = [self.rsaFile.path]
        client = SSHUserAuthClient(b"user",  options, None)
        # Populate the list of used files
        client.getPublicKey()

        def _getPassword(prompt):
            self.assertEqual(
                prompt,
                "Enter passphrase for key '%s': " % (self.rsaFile.path,))
            return nativeString(passphrase)

        def _cbGetPrivateKey(key):
            self.assertFalse(key.isPublic())
            self.assertEqual(key, rsaPrivate)

        self.patch(client, '_getPassword', _getPassword)
        return client.getPrivateKey().addCallback(_cbGetPrivateKey)


    def test_getPassword(self):
        """
        Verify that the getPassword function in L{SSHUserAuthClient}
        works, when prompt is sent, and fetching the password from the
        user succeeds.

        """
        class FakeTransport:
            def __init__(self, host):
                self.transport = self
                self.host = host
            def getPeer(self):
                return self

        options = ConchOptions()
        client = SSHUserAuthClient(b"user",  options, None)
        client.transport = FakeTransport("127.0.0.1")

        def getpass(prompt):
            self.assertEqual(prompt, "user@127.0.0.1's password: ")
            return 'bad password'

        self.patch(default.getpass, 'getpass', getpass)
        d = client.getPassword()
        d.addCallback(self.assertEqual, b'bad password')
        return d


    def test_getPasswordPrompt(self):
        """
        Verify that the getPassword function in L{SSHUserAuthClient}
        works, when prompt is sent, and fetching the password from the
        user succeeds.
        """
        options = ConchOptions()
        client = SSHUserAuthClient(b"user",  options, None)
        prompt = b"Give up your password"

        def getpass(p):
            self.assertEqual(p, nativeString(prompt))
            return 'bad password'

        self.patch(default.getpass, 'getpass', getpass)
        d = client.getPassword(prompt)
        d.addCallback(self.assertEqual, b'bad password')
        return d


    def test_getPasswordConchError(self):
        """
        Verify that the getPassword function in L{SSHUserAuthClient}
        fails it's deferred if the underlying _getPassword function
        raises a ConchError
        """
        options = ConchOptions()
        client = SSHUserAuthClient(b"user",  options, None)

        def getpass(prompt):
            raise KeyboardInterrupt("User pressed CTRL-C")

        self.patch(default.getpass, 'getpass', getpass)
        d = client.getPassword(b'?')
        self.assertFailure(d, ConchError)
