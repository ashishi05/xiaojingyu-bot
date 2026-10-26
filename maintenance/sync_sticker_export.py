"""Merge a QQ Agent export into the current AstrBot meme pack; dry run by default."""
import argparse
import json
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'AstrBot'), str(ROOT/'AstrBot/data/plugins')]
from PIL import Image
logging.getLogger("PIL").setLevel(logging.WARNING)
from meme_manager.backend.packs.resolver import resolve_pack_context
from meme_manager.backend.semantic.models import SemanticImage, normalize_tags, utc_now
from meme_manager.backend.semantic.storage import (
    file_sha256, load_metadata, save_metadata, reconcile_metadata, _write_json_atomic,
)


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sync(source, apply=False):
    export = load_json(source/'stickers-export.json')
    stickers = export['stickers']
    if not isinstance(stickers, list) or len({str(s['id']) for s in stickers}) != len(stickers):
        raise ValueError('Invalid or duplicate sticker IDs')
    context = resolve_pack_context()
    pack = Path(context['pack_dir']).resolve()
    data = pack.parent.parent
    pack.relative_to(ROOT/'AstrBot/data/plugin_data/meme_manager/packs')
    category = 'all'
    old_files = {p.relative_to(pack).as_posix():file_sha256(p) for p in (pack/'memes').rglob('*') if p.is_file()}
    by_hash = {}
    for relative, digest in old_files.items():
        by_hash.setdefault(digest, relative)
    metadata = load_metadata(pack)
    if metadata.get('metadata_read_only'):
        raise ValueError('Metadata is read-only; refusing to overwrite')
    planned, missing = [], []
    for sticker in stickers:
        filename = str(sticker.get('file') or '')
        if not filename:
            missing.append(dict(sticker, import_status='metadata_only'))
            continue
        if Path(filename).name != filename or '/' in filename or '\\' in filename:
            raise ValueError('Unsafe source filename')
        src = (source/'images'/filename).resolve()
        src.relative_to((source/'images').resolve())
        if not src.is_file():
            missing.append(dict(sticker, import_status='missing_image'))
            continue
        with Image.open(src) as image:
            if image.format not in {'PNG','JPEG','GIF','WEBP'}:
                raise ValueError('Unsupported image format')
            image.verify()
        digest = file_sha256(src)
        relative = by_hash.get(digest)
        reused = relative is not None
        if not relative:
            relative = f'memes/{category}/{filename}'
            target = pack/relative
            if target.exists() and file_sha256(target) != digest:
                relative = f'memes/{category}/{Path(filename).stem}_{digest[:12]}{Path(filename).suffix}'
                if (pack/relative).exists() and file_sha256(pack/relative) != digest:
                    raise ValueError('Destination filename conflict')
            by_hash[digest] = relative
        planned.append(dict(source=src, relative=relative, digest=digest, sticker=sticker, reused=reused))
    summary = dict(records=len(stickers), available=len(planned), new_images=sum(not r['reused'] for r in planned),
                   reused=sum(r['reused'] for r in planned), missing_images=len(missing),
                   missing_named=sum(r['import_status']=='missing_image' for r in missing),
                   metadata_only=sum(r['import_status']=='metadata_only' for r in missing),
                   available_with_tags=sum(bool(r['sticker'].get('tags')) for r in planned), old_images=len(old_files))
    if not apply:
        return summary
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = ROOT/'backups'/f'sticker-sync-{stamp}'
    backup.mkdir(parents=True)
    shutil.copytree(data, backup/'meme_manager')
    archive = data/'sticker_imports'/stamp
    archive.mkdir(parents=True)
    shutil.copy2(source/'stickers-export.json', archive/'stickers-export.json')
    _write_json_atomic(archive/'missing-images.json', {'records':missing})
    notes_path = data/'sticker_notes.json'
    notes = load_json(notes_path) if notes_path.exists() else {}
    mapping_path = pack/'memes_data.json'
    mapping = load_json(mapping_path) if mapping_path.exists() else {}
    mapping.setdefault(category, '主人收藏的表情，按每张图片的描述和标签选择，不按文件夹情绪随机选择')
    _write_json_atomic(mapping_path, mapping)
    manifest_path = pack/'manifest.json'
    manifest = load_json(manifest_path)
    manifest.setdefault('categories', {}).setdefault(category, {'description':mapping[category]})
    _write_json_atomic(manifest_path, manifest)
    receipt = []
    for row in planned:
        target = pack/row['relative']
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(row['source'], target)
        if file_sha256(target) != row['digest']:
            raise RuntimeError('Copied image checksum mismatch')
        sticker = row['sticker']
        desc = str(sticker.get('desc') or '')
        tags = normalize_tags(sticker.get('tags') or [])
        old_note = notes.get(target.name, {})
        note = dict(old_note)
        note.setdefault('note', desc)
        note['tags'] = list(dict.fromkeys([*normalize_tags(note.get('tags', [])), *tags]))
        note.setdefault('category', target.parent.name)
        notes[target.name] = note
        record = SemanticImage(content_sha256=row['digest'], relative_path=row['relative'],
            category=target.parent.name, category_description=mapping.get(target.parent.name,''),
            caption=note.get('note') or desc, tags=note['tags'], caption_status='done',
            embedding_status='pending', provenance='manual', manual_override=True,
            manual_caption=note.get('note') or desc, manual_tags=note['tags'])
        existing = metadata['images'].get(record.entry_id)
        if existing and existing.get('manual_override'):
            record = SemanticImage.from_dict(existing)
            record.manual_tags = list(dict.fromkeys([*record.manual_tags, *tags]))
            if not record.manual_caption:
                record.manual_caption = desc
            record = SemanticImage.from_dict(record.to_dict())
        metadata['images'][record.entry_id] = record.to_dict()
        receipt.append(dict(id=sticker['id'], path=row['relative'], sha256=row['digest'],
                            tags=tags, desc=desc, reused=row['reused']))
    metadata['requires_local_index_rebuild'] = True
    save_metadata(pack, metadata)
    refreshed = reconcile_metadata(pack)
    save_metadata(pack, refreshed)
    _write_json_atomic(notes_path, notes)
    # Validate preservation and imported text against the actual normalized store.
    for relative,digest in old_files.items():
        if file_sha256(pack/relative) != digest:
            raise RuntimeError('An existing image changed')
    checked = load_metadata(pack)
    for row in receipt:
        matches = [r for r in checked['images'].values() if r.get('relative_path') == row['path']]
        if len(matches) != 1 or not matches[0].get('caption') or not set(row['tags']).issubset(matches[0].get('tags', [])):
            raise RuntimeError('Imported description or tags did not survive normalization')
    all_images = [p for p in (pack/'memes').rglob('*') if p.is_file()]
    summary.update(total_images=len(all_images), backup=str(backup), archive=str(archive),
                   target=str(pack/'memes'/category), verified=True)
    _write_json_atomic(archive/'import-receipt.json', dict(summary=summary, images=receipt))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path.home() / 'Desktop')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(sync(args.source, args.apply), ensure_ascii=False, indent=2))
