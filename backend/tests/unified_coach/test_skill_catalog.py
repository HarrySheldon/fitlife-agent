from pathlib import Path
import pytest
from backend.agent.skills.catalog import SkillCatalog, SkillResourceError


def test_metadata_then_selected_content_only():
    catalog = SkillCatalog()
    summaries = catalog.search('胸训练')
    assert len(summaries) == 3
    assert all('text' not in item for item in summaries)
    text = catalog.read('skill:training-plan')['text']
    assert 'validate_training' in text
    assert '饮食回顾' not in text


@pytest.mark.parametrize('resource', ['../.env', 'C:\\secret', '\\\\server\\secret', 'https://example.com', 'skill:missing'])
def test_arbitrary_paths_are_not_resources(resource):
    with pytest.raises(SkillResourceError, match='RESOURCE_NOT_AUTHORIZED'):
        SkillCatalog().read(resource)


def test_changed_content_is_not_loaded_mid_run(tmp_path):
    import shutil
    source = Path(__file__).resolve().parents[2] / 'coach_skills'
    shutil.copytree(source, tmp_path / 'skills')
    catalog = SkillCatalog(tmp_path / 'skills')
    (tmp_path / 'skills' / 'training-plan' / 'SKILL.md').write_text('changed', encoding='utf-8')
    with pytest.raises(SkillResourceError, match='RESOURCE_VERSION_CHANGED'):
        catalog.read('skill:training-plan')


def test_added_skill_and_reference_need_no_executor_change(tmp_path):
    import json
    folder = tmp_path / 'recovery'
    folder.mkdir()
    (folder / 'references').mkdir()
    (folder / 'skill.json').write_text(json.dumps({'id': 'recovery', 'version': '1',
        'title': 'Recovery', 'description': 'Recovery advice'}), encoding='utf-8')
    (folder / 'SKILL.md').write_text('Read a reference only if needed.', encoding='utf-8')
    (folder / 'references' / 'sleep.md').write_text('Regular sleep.', encoding='utf-8')
    catalog = SkillCatalog(tmp_path)
    assert catalog.search('recovery')[0]['id'] == 'recovery'
    assert 'Regular sleep' not in str(catalog.search('recovery'))
    assert catalog.read('skill:recovery/reference:sleep')['text'] == 'Regular sleep.'


def test_resource_limit_is_not_silently_truncated(tmp_path):
    import json
    folder = tmp_path / 'large'
    folder.mkdir()
    (folder / 'skill.json').write_text(json.dumps({'id': 'large', 'version': '1',
        'title': 'Large', 'description': 'Large content'}), encoding='utf-8')
    (folder / 'SKILL.md').write_text('x' * 12001, encoding='utf-8')
    with pytest.raises(SkillResourceError, match='RESOURCE_TOO_LARGE'):
        SkillCatalog(tmp_path).read('skill:large')


def test_metadata_version_is_part_of_release_fingerprint(tmp_path):
    import json
    folder = tmp_path / 'versioned'
    folder.mkdir()
    metadata = {'id': 'versioned', 'version': '1', 'title': 'Versioned', 'description': 'Content'}
    path = folder / 'skill.json'
    path.write_text(json.dumps(metadata), encoding='utf-8')
    (folder / 'SKILL.md').write_text('Unchanged body.', encoding='utf-8')
    before = SkillCatalog(tmp_path)
    metadata['version'] = '2'
    path.write_text(json.dumps(metadata), encoding='utf-8')
    assert before.release != SkillCatalog(tmp_path).release
    with pytest.raises(SkillResourceError, match='RESOURCE_VERSION_CHANGED'):
        before.verify_release()


def test_symlink_cannot_escape_published_root(tmp_path):
    import json
    root = tmp_path / 'skills'
    folder = root / 'unsafe'
    folder.mkdir(parents=True)
    outside = tmp_path / 'outside.md'
    outside.write_text('Not a published resource', encoding='utf-8')
    (folder / 'skill.json').write_text(json.dumps({'id': 'unsafe', 'version': '1',
        'title': 'Unsafe', 'description': 'Unsafe link'}), encoding='utf-8')
    try:
        (folder / 'SKILL.md').symlink_to(outside)
    except OSError:
        pytest.skip('Windows symlink creation privilege unavailable')
    with pytest.raises(SkillResourceError, match='RESOURCE_NOT_AUTHORIZED'):
        SkillCatalog(root)
