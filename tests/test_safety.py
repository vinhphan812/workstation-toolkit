import pytest
from workstation.core.safety import SafetyError, require_execute

def test_mutation_needs_execute_and_yes():
    with pytest.raises(SafetyError): require_execute(False, False, 'dangerous')
    with pytest.raises(SafetyError): require_execute(True, False, 'dangerous')
    require_execute(True, True, 'dangerous')
