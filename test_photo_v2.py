"""Regression tests for StayVision Photo Engine V2; no credentials or network."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import cv2
import numpy as np
from PIL import Image
from ai_engine import AIEngineError,enhance_image,run_pipeline
from photo_engine_v2 import enhance_photo_v2,PhotoEngineError,_estimate_noise,_quality_metrics

class PhotoV2Tests(unittest.TestCase):
    def test_details_not_fabricated_and_upload_unchanged(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t);src=folder/'src.jpg';dst=folder/'out.jpg'
            scene=np.zeros((640,960,3),np.uint8)
            scene[:]=(85,89,94)
            cv2.rectangle(scene,(100,100),(500,490),(130,124,117),-1)
            cv2.rectangle(scene,(650,80),(890,440),(240,246,249),-1)
            cv2.line(scene,(100,100),(100,490),(24,25,25),3)
            Image.fromarray(scene).save(src,quality=85)
            original_bytes=src.read_bytes()
            meta=enhance_image(src,dst,'claro')
            self.assertEqual(src.read_bytes(),original_bytes)
            self.assertEqual(meta['size'],[960,640])
            with Image.open(dst) as image:
                rgb=np.asarray(image.convert('RGB'))
                self.assertGreater(float(rgb[300,150].mean()),float(scene[300,150].mean()))
                self.assertLess(float(np.mean(np.abs(rgb[180,800].astype(float)-scene[180,800]))),16)
            self.assertIn('source_quality',meta)
            self.assertEqual(meta['source_quality']['largura'],960)
            self.assertIn('não aplicada',meta['super_resolution'])
    def test_no_false_neural_claim_and_low_res_warning(self):
        with tempfile.TemporaryDirectory() as t:
            src=Path(t)/'tiny.png';out=Path(t)/'out.jpg'
            Image.new('RGB',(372,506),(118,122,120)).save(src)
            meta=enhance_photo_v2(src,out)
            self.assertIn('não recupera detalhes',meta['quality_notice'])
            self.assertEqual(meta['size'],[372,506])
            self.assertIn('não aplicada',meta['super_resolution'])
    def test_invalid_and_missing_model_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src=Path(t)/'a.jpg';out=Path(t)/'out.jpg'
            Image.new('RGB',(800,500),'gray').save(src)
            with self.assertRaises(AIEngineError):enhance_image(src,out,'invalid')
            with patch.dict(os.environ,{'STAYVISION_PHOTO_SUPERRES_MODEL':str(Path(t)/'missing.pb')}):
                with self.assertRaises(PhotoEngineError):enhance_photo_v2(src,out)
    def test_real_photos_pipeline_creates_quality_report(self):
        src=Path(__file__).parent/'static/assets/02_Quarto.jpg'
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)
            results=run_pipeline([src],p,mode='photo',style='premium')
            self.assertEqual(results['engine_version'],'stayvision-photo-v2.0-video-v1.0')
            self.assertTrue((p/'Fotos_StayVision.zip').is_file())
            self.assertIn('aviso_resolucao',results['photos'][0]['source_quality'])
            self.assertTrue(results['photos'][0]['quality_notice'])
            self.assertIn('noise_index',results['photos'][0])
    def test_large_image_bounds_and_opt_in_level(self):
        with tempfile.TemporaryDirectory() as t:
            src=Path(t)/'p.png';dst=Path(t)/'out.jpg'
            Image.new('RGB',(1500,1000),(128,135,138)).save(src)
            with patch.dict(os.environ,{'STAYVISION_PHOTO_AUTO_LEVEL':'1'}):
                meta=enhance_image(src,dst)
            self.assertTrue(dst.exists())
            self.assertLessEqual(abs(meta['auto_level_degrees']),2)

if __name__=='__main__':unittest.main(verbosity=2)
