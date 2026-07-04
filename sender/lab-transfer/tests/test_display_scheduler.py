from __future__ import annotations
import json, unittest
from tempest_lora_lab.display_contract import prepare_scanout_buffers
from tempest_lora_lab.display_scheduler import (
    DisplayState, FakeAtomicKmsAdapter, FakeFailurePlan, ScheduleKind,
    build_frame_schedule, run_offline_display_session,
)
from tempest_lora_lab.protocol import ProtocolError
from test_display_contract import make_artifact, make_snapshot

class DisplaySchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = make_artifact(1)
        cls.snapshot = make_snapshot()

    def run_plan(self, plan=None):
        adapter = FakeAtomicKmsAdapter(snapshot=self.snapshot, failure_plan=plan)
        return run_offline_display_session(artifact=self.artifact, snapshot=self.snapshot, adapter=adapter), adapter

    def test_schedule_is_guard_data_guard_once(self):
        schedule = build_frame_schedule(prepare_scanout_buffers(self.artifact))
        self.assertEqual([x.kind for x in schedule], [ScheduleKind.GUARD_BEFORE, ScheduleKind.DATA, ScheduleKind.GUARD_AFTER])
        self.assertEqual([x.hold_vblanks for x in schedule], [1,1,1])
        self.assertEqual(schedule[1].data_index, 0)

    def test_success_path_and_consecutive_events(self):
        result, adapter = self.run_plan()
        self.assertTrue(result.success)
        self.assertEqual(result.final_state, DisplayState.COMPLETE)
        self.assertEqual([e.sequence for e in result.events], [1001,1002,1003])
        self.assertEqual(result.commit_calls, 3)
        self.assertEqual(adapter.test_only_calls[0][1], True)
        self.assertEqual([x[1] for x in adapter.test_only_calls[1:]], [False,False])

    def test_success_manifest_is_canonical_and_records_nonclaims(self):
        result, _ = self.run_plan()
        parsed = json.loads(result.manifest_json)
        self.assertEqual(parsed['schema'], 'tempest-lora.exact-timing-display-session-manifest.v1')
        self.assertEqual(parsed['final_state'], 'COMPLETE')
        self.assertEqual(len(parsed['nonclaims']), 4)
        self.assertEqual(
            parsed['design_contract']['r2e1_contract_sha256'],
            'd6b06815ea9e4e077170067c742a87d347766bd484d63fcb1996564524a739c4',
        )
        self.assertIn('not a claim about the current checkout', parsed['design_contract']['identity_scope'])
        self.assertNotIn('repository_commit', parsed)
        self.assertNotIn('repository_tree', parsed)

    def test_deterministic_success_manifest(self):
        first, _ = self.run_plan(); second, _ = self.run_plan()
        self.assertEqual(first.manifest_json, second.manifest_json)

    def test_only_exact_fake_adapter_is_allowed(self):
        class Other: pass
        with self.assertRaises(ProtocolError):
            run_offline_display_session(artifact=self.artifact, snapshot=self.snapshot, adapter=Other())  # type: ignore[arg-type]

    def test_test_only_failure_has_no_commit_and_no_abort(self):
        result, adapter = self.run_plan(FakeFailurePlan(test_only_fail_at=1))
        self.assertFalse(result.success)
        self.assertEqual(result.commit_calls, 0)
        self.assertFalse(result.abort_black_attempted)
        self.assertEqual(adapter.commit_calls, ())

    def test_topology_change_after_preflight_has_no_commit(self):
        result, _ = self.run_plan(FakeFailurePlan(topology_change_after_preflight=True))
        self.assertFalse(result.success)
        self.assertEqual(result.commit_calls, 0)
        self.assertIn('topology changed', result.error)

    def test_commit_failure_invalidates_and_attempts_at_most_one_abort(self):
        result, adapter = self.run_plan(FakeFailurePlan(commit_fail_at=1))
        self.assertFalse(result.success)
        self.assertTrue(result.abort_black_attempted)
        self.assertLessEqual(sum(token.startswith('abort-guard:') for token in adapter.commit_calls), 1)

    def test_timeout_invalidates_without_retrying_data(self):
        result, adapter = self.run_plan(FakeFailurePlan(event_timeout_at=1))
        self.assertFalse(result.success)
        data_calls = [x for x in adapter.commit_calls if x.startswith('data:0:')]
        self.assertEqual(len(data_calls), 1)

    def test_wrong_crtc_is_rejected(self):
        result, _ = self.run_plan(FakeFailurePlan(wrong_crtc_at=1))
        self.assertFalse(result.success)
        self.assertIn('CRTC mismatch', result.error)

    def test_out_fence_error_is_rejected(self):
        result, _ = self.run_plan(FakeFailurePlan(out_fence_error_at=1))
        self.assertFalse(result.success)
        self.assertIn('out-fence', result.error)

    def test_runtime_topology_change_is_rejected_without_abort_flip(self):
        result, adapter = self.run_plan(FakeFailurePlan(runtime_topology_change_at=1))
        self.assertFalse(result.success)
        self.assertIn('during running schedule', result.error)
        self.assertFalse(result.abort_black_attempted)
        self.assertFalse(any(token.startswith('abort-guard:') for token in adapter.commit_calls))

    def test_duplicate_sequence_is_rejected(self):
        result, _ = self.run_plan(FakeFailurePlan(duplicate_sequence_at=1))
        self.assertFalse(result.success)
        self.assertIn('not consecutive', result.error)

    def test_sequence_gap_is_rejected(self):
        result, _ = self.run_plan(FakeFailurePlan(sequence_gap_at=1))
        self.assertFalse(result.success)
        self.assertIn('not consecutive', result.error)

    def test_reverse_sequence_is_rejected(self):
        result, _ = self.run_plan(FakeFailurePlan(reverse_sequence_at=1))
        self.assertFalse(result.success)
        self.assertIn('not consecutive', result.error)

    def test_final_guard_is_completed_before_success(self):
        result, adapter = self.run_plan()
        self.assertTrue(adapter.commit_calls[-1].startswith('guard:'))
        self.assertEqual(result.state_history[-2:], (DisplayState.FINAL_BLACK_PENDING, DisplayState.COMPLETE))

    def test_duplicate_monotonic_timestamp_is_rejected(self):
        result, _ = self.run_plan(FakeFailurePlan(duplicate_timestamp_at=1))
        self.assertFalse(result.success)
        self.assertIn('strictly increasing', result.error)

    def test_reverse_monotonic_timestamp_is_rejected(self):
        result, _ = self.run_plan(FakeFailurePlan(reverse_timestamp_at=1))
        self.assertFalse(result.success)
        self.assertIn('strictly increasing', result.error)

    def test_invalid_caller_snapshot_returns_deterministic_failure_manifest(self):
        invalid = make_snapshot(vrr_enabled=True)
        adapter = FakeAtomicKmsAdapter(snapshot=self.snapshot)
        result = run_offline_display_session(artifact=self.artifact, snapshot=invalid, adapter=adapter)
        self.assertFalse(result.success)
        self.assertEqual(result.commit_calls, 0)
        parsed = json.loads(result.manifest_json)
        self.assertEqual(parsed['kms_snapshot']['validation_status'], 'rejected')
        self.assertIn('vrr_enabled', parsed['kms_snapshot']['validation_error'])

    def test_failure_plan_rejects_negative_indices(self):
        with self.assertRaises(ProtocolError):
            FakeFailurePlan(commit_fail_at=-1).validate()

if __name__ == '__main__': unittest.main()
