"""Video V2 acceptance — export is real MP4, with source-sensitive resolution."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from ai_engine import render_video, AIEngineError


class VideoV2Tests(unittest.TestCase):
    def test_auto_profile_uses_720_when_photo_lacks_detail(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src=root/'tiny.jpg';out=root/'out.mp4'
            Image.new('RGB',(520,680),(80,110,135)).save(src)
            with patch.dict(os.environ,{'STAYVISION_VIDEO_QUALITY':'auto'}):
                manifest=render_video([src],out,aspect='vertical')
            self.assertEqual(manifest['resolution'],'720x1280')
            self.assertEqual(manifest['frames_per_second'],30)
            self.assertGreater(out.stat().st_size,5000)

    def test_hd_profile_real_1080_mp4(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src=root/'source.jpg';out=root/'hd.mp4'
            Image.new('RGB',(1100,1280),(110,130,160)).save(src)
            with patch.dict(os.environ,{'STAYVISION_VIDEO_QUALITY':'auto'}):
                manifest=render_video([src],out,aspect='horizontal')
            self.assertEqual(manifest['resolution'],'1920x1080')
            self.assertEqual(manifest['frames_per_second'],30)
            res=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(out)],capture_output=True,text=True,check=True)
            stream=json.loads(res.stdout)['streams'][0]
            self.assertEqual((stream['width'],stream['height']),(1920,1080))

    def test_invalid_video_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);src=root/'a.jpg';Image.new('RGB',(600,600),'gray').save(src)
            with patch.dict(os.environ,{'STAYVISION_VIDEO_QUALITY':'ultra_fake'}):
                with self.assertRaises(AIEngineError):render_video([src],root/'out.mp4')

if __name__=='__main__':unittest.main(verbosity=2)
