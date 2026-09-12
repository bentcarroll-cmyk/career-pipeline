from __future__ import annotations

import hashlib
import tempfile
import textwrap
import unittest
import zipfile
import os
import subprocess
import sys
import shutil
from pathlib import Path

from career_pipeline.packaging import PackagingError, build_plugin_archive
from career_pipeline.privacy import scan_tree
from tests.pdf_helper import write_minimal_pdf


class PackagingTests(unittest.TestCase):
    def test_archive_is_deterministic_allowlisted_and_private(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw)
            first = build_plugin_archive(repository, output / "first")
            second = build_plugin_archive(repository, output / "second")

            self.assertEqual(first.sha256, second.sha256)
            self.assertEqual(first.archive.read_bytes(), second.archive.read_bytes())
            with zipfile.ZipFile(first.archive) as bundle:
                names = bundle.namelist()
                self.assertEqual(names, sorted(names))
                self.assertIn(".codex-plugin/plugin.json", names)
                self.assertIn(".agents/plugins/marketplace.json", names)
                self.assertIn("skills/onboard/SKILL.md", names)
                self.assertIn("docs/private-beta-installation.md", names)
                self.assertIn("CHANGELOG.md", names)
                self.assertFalse(any(name.startswith("tests/") for name in names))
                self.assertFalse(any("__pycache__" in name for name in names))
                self.assertFalse(any(name.endswith((".pdf", ".doc", ".docx")) for name in names))
                self.assertTrue(
                    all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in bundle.infolist())
                )
            self.assertEqual(scan_tree(first.archive), [])
            validation = subprocess.run(
                [sys.executable, str(repository / "scripts" / "validate_plugin.py"), str(first.archive)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_archive_rejects_an_obvious_credential_bearing_runtime_member(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as raw:
            copied = Path(raw) / "repository"
            shutil.copytree(
                repository,
                copied,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"),
            )
            (copied / "src" / "career_pipeline" / "credentials.json").write_text(
                "{}", encoding="utf-8"
            )

            with self.assertRaises(PackagingError):
                build_plugin_archive(copied, Path(raw) / "dist")

    def test_archive_pdf_verifier_runs_without_site_packages(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as raw:
            temporary = Path(raw)
            package = build_plugin_archive(repository, temporary / "dist")
            extracted = temporary / "installed-plugin"
            with zipfile.ZipFile(package.archive) as bundle:
                bundle.extractall(extracted)
            workspace = temporary / "workspace"
            version = workspace / "Applications" / "JOB-000001_Synthetic" / "v001"
            version.mkdir(parents=True)
            resume = version / "Resume.pdf"
            write_minimal_pdf(resume, pages=2)
            script = "\n".join(
                (
                    "from pathlib import Path",
                    "from career_pipeline.packets import PacketRecord, collect_local_artifacts",
                    "from career_pipeline.workspace import workspace_paths",
                    f"root = Path({str(workspace)!r})",
                    "relative = Path('Applications/JOB-000001_Synthetic/v001/Resume.pdf')",
                    "record = PacketRecord(job_id='JOB-000001', employer='Synthetic', title='Lead', version='v001', version_dir=relative.parent, resume_pdf=relative, cover_letter_pdf=None, working_dir=relative.parent / 'working')",
                    "result = collect_local_artifacts(workspace_paths(root), record)",
                    "raise SystemExit(0 if result.valid else 1)",
                )
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(extracted / "src")

            result = subprocess.run(
                [sys.executable, "-S", "-c", script],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)

    def test_extracted_package_completes_synthetic_local_journey(self) -> None:
        """The archive can run the offline onboarding-to-packet path by itself."""
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as raw:
            temporary = Path(raw)
            package = build_plugin_archive(repository, temporary / "dist")
            checksum_parts = package.checksum.read_text(encoding="utf-8").split()
            self.assertEqual(checksum_parts, [package.sha256, package.archive.name])
            self.assertEqual(
                hashlib.sha256(package.archive.read_bytes()).hexdigest(),
                package.sha256,
            )
            extracted = temporary / "installed-plugin"
            with zipfile.ZipFile(package.archive) as bundle:
                bundle.extractall(extracted)
            workspace = temporary / "workspace"
            script = textwrap.dedent(
                f"""
                import hashlib
                from pathlib import Path
                from career_pipeline.backlog import build_actionable_backlog
                from career_pipeline.capabilities import CONNECTORS
                from career_pipeline.checkpoints import DiscoveryState
                from career_pipeline.discovery import ReviewedJob, deliver_reviewed_jobs
                from career_pipeline.evaluation import EvidenceClaim, JobAssessment
                from career_pipeline.onboarding import OnboardingState, advance_onboarding, record_connector_decision, record_profile_approval, save_onboarding_state
                from career_pipeline.packets import (ApplicationManifest, PacketOptions, advance_packet, collect_local_artifacts, complete_local_delivery, start_packet, verify_local_artifacts)
                from career_pipeline.quality import QualityReceipt
                from career_pipeline.readiness import check_readiness
                from career_pipeline.schema import diagnose_workspace
                from career_pipeline.sources.base import CandidateJob
                from career_pipeline.workspace import create_workspace, preserve_source_resume

                def write_pdf(path):
                    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>', b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>', b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R >>', b'<< /Length 0 >>\\nstream\\n\\nendstream']
                    data = bytearray(b'%PDF-1.4\\n%synthetic\\n'); offsets = [0]
                    for number, body in enumerate(objects, 1):
                        offsets.append(len(data)); data.extend(f'{{number}} 0 obj\\n'.encode()); data.extend(body); data.extend(b'\\nendobj\\n')
                    xref = len(data); data.extend(f'xref\\n0 {{len(objects) + 1}}\\n'.encode()); data.extend(b'0000000000 65535 f \\n')
                    for offset in offsets[1:]: data.extend(f'{{offset:010d}} 00000 n \\n'.encode())
                    data.extend(f'trailer\\n<< /Size {{len(objects) + 1}} /Root 1 0 R >>\\nstartxref\\n{{xref}}\\n%%EOF\\n'.encode()); path.write_bytes(data)

                workspace = create_workspace(Path({str(workspace)!r}))
                profile = workspace.profile / 'Career_Profile.md'; criteria = workspace.profile / 'Search_Criteria.md'; preferences = workspace.profile / 'Writing_Preferences.md'
                profile.write_text('EV-SYN-001: Synthetic evidence.\\n', encoding='utf-8'); criteria.write_text('Synthetic criteria.\\n', encoding='utf-8'); preferences.write_text('Synthetic preferences.\\n', encoding='utf-8')
                source = workspace.root.parent / 'Synthetic_Resume.txt'; source.write_text('Synthetic resume.\\n', encoding='utf-8'); preserve_source_resume(source, workspace)
                profile_hash = hashlib.sha256(profile.read_bytes()).hexdigest(); criteria_hash = hashlib.sha256(criteria.read_bytes()).hexdigest(); preferences_hash = hashlib.sha256(preferences.read_bytes()).hexdigest()
                state = OnboardingState.quick_start()
                state = advance_onboarding(state, 'workspace', {{'privacy_approved': True}})
                state = advance_onboarding(state, 'resume', {{'workspace_root': str(workspace.root)}})
                state = advance_onboarding(state, 'focus', {{'resume_receipt': 'State/source-resume-receipt.json'}})
                state = advance_onboarding(state, 'profile', {{'target_work': ['Operations leadership'], 'hard_constraints': []}})
                state = record_profile_approval(state, profile_hash, criteria_hash)
                state = advance_onboarding(state, 'packet_defaults', {{'profile_approved': True, 'criteria_approved': True}})
                state = advance_onboarding(state, 'connectors', {{'resume_pages': 2, 'cover_letter_enabled': False}})
                for connector in CONNECTORS: state = record_connector_decision(state, connector, 'declined', ())
                state = advance_onboarding(state, 'schedule', {{}})
                state = advance_onboarding(state, 'readiness', {{'enabled_sources': ['public_ats']}})
                config = {{'schema_version': 2, 'workspace_root': str(workspace.root), 'timezone': 'America/New_York', 'enabled_sources': ['public_ats'], 'discovery_schedule': {{'frequency':'weekday','weekdays':['MO'],'runs_per_day':1,'timezone':'America/New_York'}}, 'paths': {{'profile':'Profile','sources':'Sources','jobs':'Jobs','applications':'Applications','indexes':'Indexes','runs':'Runs','state':'State'}}, 'profile_approved': True, 'criteria_approved': True, 'connectors': {{name: {{'decision':'declined','capabilities':[]}} for name in CONNECTORS}}, 'packet_defaults': {{'resume_pages':2,'cover_letter_enabled':False,'cover_letter_pages':0}}}}
                (workspace.state / 'config.json').write_text(__import__('json').dumps(config), encoding='utf-8')
                save_onboarding_state(workspace.state / 'onboarding-state.json', state)
                assert check_readiness(config, state).ready
                state = advance_onboarding(state, 'active', {{'ready': True}})
                save_onboarding_state(workspace.state / 'onboarding-state.json', state)
                candidate = CandidateJob(source='public-search', source_record_id='synthetic-record', requisition_id='SYN-601', employer='Example Cooperative', title='Director of Operations', responsibilities=('Lead synthetic operations.',), location='Example City', workplace_model='hybrid', travel=None, compensation_evidence=None, posting_url='https://jobs.example/postings/SYN-601', application_url='https://jobs.example/apply/SYN-601', team='Operations', posted_at='2026-09-10T12:00:00Z', updated_at=None, deadline=None, verified_at='2026-09-11T12:00:00Z', verification_status='verified', raw_field_hash='a' * 64, uncertainties=())
                assessment = JobAssessment('strong_match', 'Synthetic evidence supports the role.', (EvidenceClaim('EV-SYN-001', 'Synthetic evidence.'),), (), (), profile_hash=profile_hash, criteria_hash=criteria_hash)
                outcome = deliver_reviewed_jobs(workspace, DiscoveryState(), (ReviewedJob(candidate, assessment, '# Synthetic posting\\n', '# Synthetic assessment\\n'),), occurred_at='2026-09-11T12:05:00Z')
                assert outcome.created_job_ids == ('JOB-000001',)
                backlog = build_actionable_backlog(workspace, as_of='2026-09-11T12:06:00Z')
                assert backlog['actions'][0]['job_id'] == 'JOB-000001'
                options = PacketOptions(False, 2, 0, profile_hash, criteria_hash, preferences_hash, '')
                manifest, record = start_packet(workspace, 'JOB-000001', options, ApplicationManifest(), occurred_at='2026-09-11T12:10:00Z', explicit_request=True)
                write_pdf(workspace.root / record.resume_pdf); hashes = collect_local_artifacts(workspace, record).hashes
                manifest = advance_packet(manifest, 'JOB-000001', 'posting_verified', {{'posting_url': candidate.posting_url, 'application_url': candidate.application_url, 'posting_snapshot_hash': 'b' * 64}})
                manifest = advance_packet(manifest, 'JOB-000001', 'drafted', {{'draft_hashes': {{'resume': 'a' * 64}}}}); record = manifest.packets['JOB-000001'][-1]
                receipt = QualityReceipt.all_passed(2, None).as_dict(); receipt['bindings'] = {{'profile_hash': record.profile_hash, 'criteria_hash': record.criteria_hash, 'writing_preferences_hash': record.writing_preferences_hash, 'packet_options': dict(record.packet_options), 'role_instructions': record.role_instructions, 'posting_snapshot_hash': 'b' * 64, 'draft_hashes': {{'resume': 'a' * 64}}, 'final_pdf_hashes': dict(hashes)}}
                manifest = advance_packet(manifest, 'JOB-000001', 'quality_checked', receipt); manifest = advance_packet(manifest, 'JOB-000001', 'saved', {{'artifact_hashes': hashes}}); manifest = complete_local_delivery(workspace, manifest, 'JOB-000001', occurred_at='2026-09-11T12:15:00Z')
                assert manifest.packets['JOB-000001'][-1].stage == 'ready'; assert verify_local_artifacts(workspace, manifest.packets['JOB-000001'][-1]).valid
                findings = diagnose_workspace(workspace.root)
                assert findings == (), findings
                """
            )
            environment = dict(os.environ)
            environment["PYTHONPATH"] = str(extracted / "src")
            result = subprocess.run(
                [sys.executable, "-S", "-c", script],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
