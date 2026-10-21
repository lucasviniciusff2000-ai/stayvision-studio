"""Quality and safety acceptance tests — StayVision Photo Engine V3."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from PIL import Image
from ai_engine import enhance_image, run_pipeline, AIEngineError
from photo_engine_v3 import enhance_photo_v3, _scene_metrics


class PhotoEngineV3Tests(unittest.TestCase):
    def test_detailed_quality_report_and_untouched_source(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work)
            arr=np.zeros((800,1200,3),np.uint8)
            arr[:]=(109,108,101)
            arr[:200]=(165,190,213)  # sky
            arr[200:700,80:550]=(59,65,62)  # wall in shadow
            arr[300:650,680:1100]=(150,176,190)
            orig=root/'source.png';target=root/'processed.jpg'
            Image.fromarray(arr).save(orig)
            digest=orig.read_bytes()
            meta=enhance_photo_v3(orig,target,'claro')
            self.assertEqual(orig.read_bytes(),digest)
            self.assertTrue(target.is_file())
            self.assertEqual(meta['size'],[1200,800])
            self.assertEqual(meta['original_size'],[1200,800])
            result=cv2.cvtColor(cv2.imread(str(target)),cv2.COLOR_BGR2RGB)
            self.assertGreater(result[400,220].mean(),arr[400,220].mean()+3)
            self.assertLess(abs(float(result[100,200].mean())-float(arr[100,200].mean())),15)
            self.assertIn('scene_indicators_before',meta)
            self.assertIn('quality_guard',meta)
            self.assertIn('não aplicada',meta['super_resolution'])

    def test_strong_blue_is_not_pushed_to_neon(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work)
            arr=np.full((700,1000,3),(15,185,230),dtype=np.uint8)
            src=root/'cyan.png';dest=root/'cyan.jpg'
            Image.fromarray(arr).save(src)
            enhance_photo_v3(src,dest,style='premium')
            with Image.open(dest) as output:
                result=np.asarray(output)
            s1=cv2.cvtColor(arr,cv2.COLOR_RGB2HSV)[:,:,1].mean()
            s2=cv2.cvtColor(result,cv2.COLOR_RGB2HSV)[:,:,1].mean()
            self.assertLess(s2,s1+6)

    def test_original_output_not_generated_by_simple_enlarge(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work);src=root/'small.png';dest=root/'edited.jpg'
            Image.new('RGB',(500,420),(90,115,125)).save(src)
            meta=enhance_photo_v3(src,dest)
            self.assertEqual(meta['size'],[500,420])
            self.assertIsNotNone(meta['quality_notice'])
            self.assertIn('não aplicada',meta['super_resolution'])

    def test_manifest_contact_sheet_and_report_private_data_free(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work)
            src=root/'input.jpg';Image.new('RGB',(640,420),(118,129,132)).save(src)
            manifest=run_pipeline([src],root/'job',mode='photo')
            self.assertEqual(manifest['engine_version'],'stayvision-photo-v3.0-video-v3.0')
            labels={e['type'] for e in manifest['artifacts']}
            self.assertTrue({'photos','review','qa','manifest'}.issubset(labels))
            self.assertTrue((root/'job'/'Comparativo_StayVision_V3.jpg').exists())
            report=json.loads((root/'job'/'Relatorio_Qualidade_V3.json').read_text())
            self.assertEqual(report['engine'],'V3')
            self.assertEqual(report['photos'][0]['size'],[640,420])

    def test_invalid_model_path_fails_closed_without_altering_source(self):
        with tempfile.TemporaryDirectory() as work:
            root=Path(work);src=root/'a.png';dest=root/'a.jpg'
            Image.new('RGB',(700,450),'white').save(src)
            original=src.read_bytes()
            with patch.dict(os.environ,{'STAYVISION_PHOTO_SUPERRES_MODEL':str(root/'no.pb')}):
                with self.assertRaises(AIEngineError):enhance_image(src,dest)
            self.assertFalse(dest.exists())
            self.assertEqual(original,src.read_bytes())

if __name__=='__main__':unittest.main(verbosity=2)
