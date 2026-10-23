"""Discover metadata, then read individual version-pinned resources."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re


class SkillResourceError(ValueError):
    pass


@dataclass(frozen=True)
class SkillMetadata:
    id: str
    version: str
    title: str
    description: str
    resource_ids: tuple[str, ...]
    digest: str


class SkillCatalog:
    def __init__(self, root=None):
        self.root = Path(root or Path(__file__).resolve().parents[2] / 'coach_skills').resolve()
        self._resources = {}
        self._skills = []
        self._manifests = {}
        for folder in sorted(self.root.iterdir()):
            if not folder.is_dir():
                continue
            meta_path = folder / 'skill.json'
            if not meta_path.is_file():
                continue
            meta = json.loads(self._inside(meta_path).read_text(encoding='utf-8'))
            self._manifests[meta_path] = hashlib.sha256(self._inside(meta_path).read_bytes()).hexdigest()
            skill_id = meta['id']
            if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', skill_id) or folder.name != skill_id:
                raise SkillResourceError('INVALID_SKILL_ID')
            paths = [('skill:' + skill_id, folder / 'SKILL.md')]
            for ref in sorted((folder / 'references').glob('*.md')):
                if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', ref.stem):
                    raise SkillResourceError('INVALID_RESOURCE_ID')
                paths.append((f'skill:{skill_id}/reference:{ref.stem}', ref))
            digests = [self._manifests[meta_path]]
            for resource_id, path in paths:
                if resource_id in self._resources:
                    raise SkillResourceError('DUPLICATE_RESOURCE_ID')
                data = self._inside(path).read_bytes()
                digest = hashlib.sha256(data).hexdigest()
                self._resources[resource_id] = (path, digest)
                digests.append(digest)
            self._skills.append(SkillMetadata(skill_id, meta['version'], meta['title'],
                meta['description'], tuple(key for key, _ in paths),
                hashlib.sha256(''.join(digests).encode()).hexdigest()))
        self.release = hashlib.sha256(''.join(item.digest for item in self._skills).encode()).hexdigest()

    def verify_release(self):
        try:
            for path, digest in [*self._manifests.items(), *self._resources.values()]:
                if hashlib.sha256(self._inside(path).read_bytes()).hexdigest() != digest:
                    raise SkillResourceError('RESOURCE_VERSION_CHANGED')
        except (OSError, UnicodeError) as error:
            raise SkillResourceError('RESOURCE_VERSION_CHANGED') from error

    def _inside(self, path):
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(self.root):
            raise SkillResourceError('RESOURCE_NOT_AUTHORIZED')
        return resolved

    def search(self, query, limit=8):
        self.verify_release()
        if not isinstance(query, str) or len(query) > 500 or type(limit) is not int or not 1 <= limit <= 8:
            raise SkillResourceError('INVALID_SKILL_SEARCH')
        terms = set(query.lower())
        ranked = sorted(self._skills, key=lambda item: (
            -len(terms & set((item.title + item.description + item.id).lower())), item.id))
        return [asdict(item) for item in ranked[:limit]]

    def read(self, resource_id, expected_digest=None):
        self.verify_release()
        entry = self._resources.get(resource_id)
        if entry is None:
            raise SkillResourceError('RESOURCE_NOT_AUTHORIZED')
        path, digest = entry
        data = self._inside(path).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest or expected_digest not in (None, digest):
            raise SkillResourceError('RESOURCE_VERSION_CHANGED')
        text = data.decode('utf-8')
        if len(text) > 12000:
            raise SkillResourceError('RESOURCE_TOO_LARGE')
        return {'resource_id': resource_id, 'text': text, 'digest': digest,
                'source': 'published_skill', 'release': self.release}
