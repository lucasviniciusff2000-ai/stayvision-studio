"""Video V3: pixel stability, proper fades, file integrity and old V2 API."""
import json
import math
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageDraw
from ai_engine import render_video, AIEngineError
from video_engine_v3 import (FPS,SCENE_SECONDS,CROSSFADE_FRAMES,MOTIONS,
    ease,crossfade_weight,frame_transform,steady_frame,render_steady_video,SteadyVideoError)

class VideoV3Tests(unittest.TestCase):
    def test_easing_has_zero_boundary_velocity_and_monotonic(self):
        points=[ease(i/1000) for i in range(1001)]
        self.assertEqual(points[0],0)
        self.assertEqual(points[-1],1)
        self.assertTrue(all(b>=a for a,b in zip(points,points[1:])))
        self.assertLess(points[1],1e-6)
        self.assertLess(1-points[-2],1e-6)

    def test_subpixel_motion_is_small_without_instant_jumps(self):
        for i in range(4):
            matrices=[frame_transform((1280,720),i,k/119) for k in range(120)]
            jumps=[np.max(np.abs(b-a)) for a,b in zip(matrices,matrices[1:])]
            self.assertLess(max(jumps),0.35, (i,max(jumps)))
            self.assertGreater(max(jumps),0)
            # Transition out at near-zero velocity.
            self.assertLess(jumps[-1],max(jumps)*0.01)

    def test_static_never_moves(self):
        canvas=np.random.default_rng(1).integers(0,256,(100,150,3),dtype=np.uint8)
        frame=steady_frame(canvas,2,55,120,motion='static')
        self.assertTrue(np.array_equal(frame,canvas))

    def test_affine_preserves_dimensions_lines_and_no_black_borders(self):
        canvas=np.full((180,320,3),170,dtype=np.uint8)
        cv2.line(canvas,(35,10),(35,170),(20,20,20),4)
        for idx in [0,30,60,90,119]:
            frame=steady_frame(canvas,0,idx,120)
            self.assertEqual(frame.shape,canvas.shape)
            self.assertGreater(frame[0,0].mean(),110)
            self.assertLess(frame[80:100,25:55].min(),100)

    def test_crossfade_has_soft_start_and_end(self):
        weights=[crossfade_weight(i,15) for i in range(15)]
        self.assertEqual(len(weights),15)
        self.assertGreater(weights[0],0)
        self.assertLess(weights[-1],1)
        self.assertTrue(all(b>a for a,b in zip(weights,weights[1:])))
        self.assertLess(weights[0],0.02)
        self.assertGreater(weights[-1],0.98)

    def test_two_scene_render_time_and_output_format(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            one=root/'room1.png';two=root/'room2.png';output=root/'movie.mp4'
            for path,color in [(one,(80,150,190)),(two,(160,125,70))]:
                img=Image.new('RGB',(500,300),color);d=ImageDraw.Draw(img)
                for x in range(20,480,40):d.line((x,0,x,299),fill=(230,230,230),width=2)
                img.save(path)
            with patch.dict(os.environ,{'STAYVISION_VIDEO_QUALITY':'balanced','STAYVISION_VIDEO_MOTION':'minimal'}):
                report=render_video([one,two],output,aspect='horizontal')
            expected_frames=2*FPS*SCENE_SECONDS-CROSSFADE_FRAMES
            self.assertEqual(report['frame_count'],expected_frames)
            self.assertEqual(report['duration_seconds'],expected_frames/FPS)
            self.assertEqual(report['transition_seconds'],CROSSFADE_FRAMES/FPS)
            self.assertEqual(report['resolution'],'1280x720')
            self.assertGreater(output.stat().st_size,10000)
            meta=subprocess.run(['ffprobe','-v','error','-select_streams','v:0',
                 '-show_entries','stream=width,height,r_frame_rate,nb_frames','-of','json',str(output)],capture_output=True,text=True,check=True)
            stream=json.loads(meta.stdout)['streams'][0]
            self.assertEqual(stream['nb_frames'],str(expected_frames))
            self.assertEqual(stream['r_frame_rate'],'30/1')

    def test_invalid_config_and_empty_list_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            src=Path(t)/'a.png';Image.new('RGB',(500,300),'red').save(src)
            with self.assertRaises(SteadyVideoError):render_steady_video([],Path(t)/'x.mp4')
            with self.assertRaises(SteadyVideoError):render_steady_video([src],Path(t)/'x.mp4',motion='shaky')
            with self.assertRaises(AIEngineError):
                with_invalid=patch.dict(os.environ,{'STAYVISION_VIDEO_MOTION':'unknown'})
                with with_invalid:
                    render_video([src],Path(t)/'x.mp4')

if __name__=='__main__':unittest.main()
