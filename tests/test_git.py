from unittest.mock import patch
from workstation.core.git import is_bad_identity, is_good_identity, GitIdentity, RepoIdentity

def test_identifies_bad_hermes_identity():
    assert is_bad_identity("hermes@agent.local")
    assert is_bad_identity("some-hermes-agent@domain.test")
    assert not is_bad_identity("vinhphan812@gmail.com")

def test_identifies_expected_good_identity():
    assert is_good_identity("vinhphan812@gmail.com")
    assert is_good_identity("hermes-devops@opsswarm.local")
    assert not is_good_identity("hermes@agent.local")
