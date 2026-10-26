import os, sys
from pathlib import Path
_DEPLOYMENT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(_DEPLOYMENT_ROOT / 'AstrBot')
sys.path.insert(0, str(_DEPLOYMENT_ROOT / 'maintenance'))

import json, tempfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import sync_sticker_export as mod
from meme_manager.backend.semantic.models import SemanticImage
from meme_manager.backend.semantic.storage import save_metadata, file_sha256
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    pack=root/'AstrBot/data/plugin_data/meme_manager/packs/test'
    (pack/'memes/happy').mkdir(parents=True)
    Image.new('RGB',(2,2),'red').save(pack/'memes/happy/old.png')
    old=pack/'memes/happy/old.png'
    record=SemanticImage(content_sha256=file_sha256(old),relative_path='memes/happy/old.png',category='happy',caption='original',tags=['old'],manual_caption='original',manual_tags=['old'],manual_override=True,provenance='manual',caption_status='done')
    (pack/'memes_data.json').write_text(json.dumps({'happy':'开心'}),encoding='utf-8')
    (pack/'manifest.json').write_text(json.dumps({'id':'test','categories':{'happy':{'description':'开心'}}}),encoding='utf-8')
    save_metadata(pack,{'images':{record.entry_id:record.to_dict()}})
    source=root/'source'
    (source/'images').mkdir(parents=True)
    Image.new('RGB',(2,2),'red').save(source/'images/repeated.png')
    Image.new('RGB',(2,2),'blue').save(source/'images/new.png')
    stickers=[dict(id='1',file='repeated.png',desc='imported',tags=['red']),dict(id='2',file='new.png',desc='new',tags=['blue']),dict(id='3',file='missing.png',desc='missing',tags=['missing']),dict(id='4',file='',desc='no image',tags=[])]
    (source/'stickers-export.json').write_text(json.dumps({'stickers':stickers}),encoding='utf-8')
    with patch.object(mod,'ROOT',root), patch.object(mod,'resolve_pack_context',return_value={'pack_dir':str(pack)}):
        before=mod.sync(source)
        assert before['new_images']==1 and before['reused']==1 and before['missing_images']==2, before
        after=mod.sync(source,True)
        assert after['total_images']==2 and after['verified'],after
        md=mod.load_metadata(pack)
        assert md['images'][record.entry_id]['caption']=='original'
        assert set(md['images'][record.entry_id]['tags']) >= {'old','red'}
        again=mod.sync(source)
        assert again['new_images']==0 and again['reused']==2,again
        bad=stickers+[dict(id='5',file='../escape.png')]
        (source/'stickers-export.json').write_text(json.dumps({'stickers':bad}),encoding='utf-8')
        try:mod.sync(source)
        except ValueError:pass
        else:raise AssertionError('unsafe path accepted')
print('PASS: merge, hash deduplication, existing manual annotations, missing-image archive, repeat import, unsafe path')
