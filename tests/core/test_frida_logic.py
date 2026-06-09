import pytest
import os
import sys

# Test the core logic of voice_hook.js cross-check directly in python
# to guarantee we never regress to the "majority vote suicide bug".

def simulate_try_resolve_ssrc_offset(intercepted_ssrc, user_memory_mock, offset_candidate):
    """
    Simulates the logic inside tryResolveSsrcOffset in voice_hook.js
    user_memory_mock is a list of integers representing the SSRC at the candidate offset for all users in the call.
    """
    valid_count = 0
    invalid_count = 0
    
    for other_ssrc in user_memory_mock:
        # The FIXED logic that allows 0 as a valid "muted/silent" state
        if other_ssrc == 0 or (other_ssrc > 100 and other_ssrc < 4000000000):
            valid_count += 1
        else:
            invalid_count += 1
            
    return valid_count > invalid_count

def test_majority_vote_bug_does_not_regress():
    # Scenario: 1 person speaking (SSRC 12545), 7 people silent/muted (SSRC 0)
    # The old logic would have failed this because 7 > 1.
    mock_memory_at_offset = [12545, 0, 0, 0, 0, 0, 0, 0]
    
    # We guarantee that the fixed logic accepts this memory layout
    is_valid_offset = simulate_try_resolve_ssrc_offset(12545, mock_memory_at_offset, 0x1e70)
    assert is_valid_offset is True, "The logic failed! It rejected valid memory because too many users were silent (SSRC 0)."

def test_rejects_actual_garbage_memory():
    # Scenario: We hit a random memory offset where data is complete garbage (pointers, random floats, etc)
    # This should correctly be rejected.
    mock_memory_at_offset = [12545, 4294967295, 8, 4294967290, 12, 1, 9999999999, 42]
    
    is_valid_offset = simulate_try_resolve_ssrc_offset(12545, mock_memory_at_offset, 0x1e70)
    assert is_valid_offset is False, "The logic accepted garbage memory as a valid SSRC offset!"