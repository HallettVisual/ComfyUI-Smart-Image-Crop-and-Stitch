import importlib.util
import sys
import unittest
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "smart_image_tools"
# The loader nodes import ComfyUI modules; run from inside a ComfyUI custom_nodes folder.
sys.path.insert(0, str(ROOT.parents[1]))

spec = importlib.util.spec_from_file_location(
    PACKAGE_NAME,
    ROOT / "__init__.py",
    submodule_search_locations=[str(ROOT)],
)
package = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE_NAME] = package
spec.loader.exec_module(package)

from smart_image_tools.common_image import _gaussian_blur
from smart_image_tools.image_comparer import ImageComparer
from smart_image_tools.smart_image_crop import SmartImageCrop
from smart_image_tools.smart_image_stitcher import SmartImageStitcher


class SmartImageToolsSmokeTest(unittest.TestCase):
    def test_empty_mask_bypasses_crop_and_stitcher(self):
        image = torch.rand(1, 64, 64, 3)
        mask = torch.zeros(1, 64, 64)

        crop_image, crop_mask, info, overlay = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=32,
            patch_mask_holes=True,
            no_mask_mode="Bypass",
            force_divisibility=64,
        )

        self.assertTrue(info["bypass"])
        self.assertTrue(torch.equal(crop_image, image))
        self.assertTrue(torch.equal(crop_mask, mask))
        self.assertTrue(torch.equal(overlay, image))

        stitched, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=torch.zeros_like(image),
            stitcher_info=info,
            feather_pixels=32,
            blend_mode="Box Feather",
            enable_color_match=True,
            color_match_amount=1.0,
        )

        self.assertTrue(torch.equal(stitched, image))

    def test_small_blur_does_not_crash(self):
        blurred = _gaussian_blur(torch.ones(1, 4, 4), blur_px=32)
        self.assertEqual(tuple(blurred.shape), (1, 4, 4))

    def test_color_match_path_stitches(self):
        image = torch.full((1, 32, 32, 3), 0.25)
        processed = torch.full((1, 16, 16, 3), 0.9)
        info = {
            "bypass": False,
            "x": [8],
            "y": [8],
            "w": [16],
            "h": [16],
            "padL": [0],
            "padT": [0],
        }

        stitched, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=processed,
            stitcher_info=info,
            feather_pixels=0,
            blend_mode="Hard Paste",
            enable_color_match=True,
            color_match_amount=1.0,
        )

        self.assertEqual(tuple(stitched.shape), tuple(image.shape))
        self.assertLess(float(stitched[:, 8:24, 8:24, :].mean()), 0.9)

    def test_color_match_is_disabled_by_default(self):
        image = torch.full((1, 32, 32, 3), 0.25)
        processed = torch.full((1, 16, 16, 3), 0.9)
        info = {
            "bypass": False,
            "x": [8],
            "y": [8],
            "w": [16],
            "h": [16],
            "padL": [0],
            "padT": [0],
        }

        stitched, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=processed,
            stitcher_info=info,
            feather_pixels=0,
            blend_mode="Hard Paste",
        )

        self.assertAlmostEqual(float(stitched[:, 8:24, 8:24, :].mean()), 0.9, places=5)

    def test_small_auto_crop_snaps_up_to_divisible_dimensions(self):
        image = torch.rand(1, 512, 512, 3)
        mask = torch.zeros(1, 512, 512)
        mask[:, 240:260, 240:260] = 1.0

        crop_image, _, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=2048,
            min_resolution=1000,
            manual_width=513,
            manual_height=777,
            mask_grow_pixels=0,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=128,
        )

        self.assertEqual(tuple(crop_image.shape[1:3]), (1024, 1024))
        self.assertEqual(info["target_w"], [1024])
        self.assertEqual(info["target_h"], [1024])

    def test_light_grey_mask_is_detected_and_solidified(self):
        image = torch.rand(1, 256, 256, 3)
        mask = torch.zeros(1, 256, 256)
        mask[:, 100:120, 100:120] = 0.05

        _, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=64,
        )

        self.assertFalse(info["bypass"])
        self.assertEqual(float(crop_mask.max()), 1.0)

    def test_patch_mask_holes_fills_enclosed_empty_area(self):
        image = torch.rand(1, 256, 256, 3)
        mask = torch.zeros(1, 256, 256)
        mask[:, 80:176, 80:176] = 1.0
        mask[:, 112:144, 112:144] = 0.0

        _, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=True,
            no_mask_mode="Bypass",
            force_divisibility=64,
        )

        self.assertFalse(info["bypass"])
        self.assertEqual(float(crop_mask.min()), 1.0)

    def test_empty_mask_can_resize_full_image_to_max_resolution(self):
        image = torch.rand(1, 600, 900, 3)
        mask = torch.zeros(1, 600, 900)

        crop_image, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=True,
            no_mask_mode="Resize Full Image",
            force_divisibility=128,
        )

        self.assertFalse(info["bypass"])
        self.assertEqual(tuple(crop_image.shape[1:3]), (768, 1024))
        self.assertEqual(tuple(crop_mask.shape[1:3]), (768, 1024))
        self.assertEqual(info["w"], [900])
        self.assertEqual(info["h"], [600])
        self.assertTrue(info["full_image_resize"])

        restored, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=crop_image,
            stitcher_info=info,
            feather_pixels=0,
            blend_mode="Hard Paste",
            resize_full_image_output="Restore Original Size",
        )
        kept, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=crop_image,
            stitcher_info=info,
            feather_pixels=0,
            blend_mode="Hard Paste",
            resize_full_image_output="Keep Resized Image",
        )

        self.assertEqual(tuple(restored.shape), tuple(image.shape))
        self.assertEqual(tuple(kept.shape), tuple(crop_image.shape))

    def test_mask_grow_and_shrink_affect_crop_bounds(self):
        image = torch.rand(1, 256, 256, 3)
        mask = torch.zeros(1, 256, 256)
        mask[:, 100:156, 100:156] = 1.0

        _, _, grown_info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Manual",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=16,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=64,
        )
        _, _, shrunk_info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Manual",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=-16,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=64,
        )

        self.assertGreater(grown_info["w"][0], shrunk_info["w"][0])

    def test_mask_feather_fades_out_at_crop_border(self):
        image = torch.zeros(1, 256, 256, 3)
        mask = torch.zeros(1, 256, 256)
        mask[:, 96:160, 96:160] = 1.0

        crop_image, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Manual",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=64,
        )

        stitched, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=torch.ones_like(crop_image),
            stitcher_info=info,
            feather_pixels=16,
            blend_mode="Mask Feather",
            mask=crop_mask,
        )

        x, y, w, h = info["x"][0], info["y"][0], info["w"][0], info["h"][0]
        self.assertLess(float(stitched[0, y, x:x + w].max()), 0.01)
        self.assertLess(float(stitched[0, y:y + h, x].max()), 0.01)
        self.assertGreater(float(stitched[0, 128, 128].min()), 0.99)

    def test_large_feather_still_stitches_small_crop(self):
        image = torch.zeros(1, 512, 512, 3)
        mask = torch.zeros(1, 512, 512)
        mask[:, 200:300, 200:300] = 1.0

        crop_image, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=2048,
            min_resolution=1024,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=True,
            no_mask_mode="Bypass",
            force_divisibility=64,
            context_padding=0,
        )

        stitched, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=torch.ones_like(crop_image),
            stitcher_info=info,
            feather_pixels=64,
            blend_mode="Mask Feather",
            feather_mode="Pixels",
            mask=crop_mask,
        )

        self.assertGreater(float(stitched[0, 250, 250].min()), 0.9)

    def test_rgba_processed_image_stitches_into_rgb(self):
        image = torch.zeros(1, 512, 512, 3)
        mask = torch.zeros(1, 512, 512)
        mask[:, 200:300, 200:300] = 1.0

        crop_image, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=2048,
            min_resolution=1024,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=True,
            no_mask_mode="Bypass",
            force_divisibility=64,
            context_padding=16,
        )
        rgba = torch.ones(*crop_image.shape[:3], 4)

        stitched, = SmartImageStitcher().stitch(
            original_image=image,
            processed_image=rgba,
            stitcher_info=info,
            feather_pixels=0,
            blend_mode="Mask Feather",
            enable_color_match=True,
            mask=crop_mask,
        )

        self.assertEqual(stitched.shape[-1], 3)
        # Colour match pulls the white patch toward the black original, but the patch is still pasted.
        self.assertGreater(float(stitched[0, 250, 250].min()), 0.5)

    def test_auto_feather_scales_with_crop_size(self):
        def soft_edge_width(size):
            image = torch.zeros(1, 1024, 1024, 3)
            info = {"bypass": False, "x": [100], "y": [100], "w": [size], "h": [size], "padL": [0], "padT": [0]}
            stitched, = SmartImageStitcher().stitch(
                original_image=image,
                processed_image=torch.ones(1, 64, 64, 3),
                stitcher_info=info,
                feather_pixels=0,
                blend_mode="Box Feather",
            )
            row = stitched[0, 100 + size // 2, 100:100 + size, 0]
            return int(((row > 0.01) & (row < 0.99)).sum())

        small, large = soft_edge_width(50), soft_edge_width(600)
        self.assertGreater(small, 0)
        self.assertLess(small, 20)
        self.assertGreater(large, small * 5)

    def test_context_padding_expands_crop_but_not_mask(self):
        image = torch.rand(1, 512, 512, 3)
        mask = torch.zeros(1, 512, 512)
        mask[:, 224:288, 224:288] = 1.0

        _, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Manual",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=64,
            context_padding=32,
        )

        self.assertEqual(info["w"][0], 128)
        self.assertAlmostEqual(float(crop_mask.mean()), 0.25, places=2)

    def test_empty_mask_can_crop_full_image(self):
        image = torch.rand(1, 600, 900, 3)
        mask = torch.zeros(1, 600, 900)

        crop_image, crop_mask, info, _ = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=1024,
            min_resolution=512,
            manual_width=512,
            manual_height=512,
            mask_grow_pixels=0,
            patch_mask_holes=True,
            no_mask_mode="Crop Full Image",
            force_divisibility=128,
        )

        self.assertFalse(info["bypass"])
        self.assertEqual(tuple(crop_image.shape), tuple(image.shape))
        self.assertEqual(float(crop_mask.min()), 1.0)

    def test_comparer_previews_both_images(self):
        ui = ImageComparer().compare(image_a=torch.rand(2, 32, 32, 3), image_b=torch.rand(1, 32, 32, 3))["ui"]

        self.assertEqual(len(ui["a_images"]), 2)
        self.assertEqual(len(ui["b_images"]), 1)
        self.assertEqual(ui["a_images"][0]["type"], "temp")
        self.assertEqual(ImageComparer().compare()["ui"], {"a_images": [], "b_images": []})

    def _crop_large_mask(self, **kwargs):
        image = torch.rand(1, 3000, 4000, 3)
        mask = torch.zeros(1, 3000, 4000)
        mask[:, 500:2500, 1000:3000] = 1.0
        return image, mask, SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=2048,
            min_resolution=1024,
            manual_width=1024,
            manual_height=1024,
            mask_grow_pixels=0,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=64,
            **kwargs,
        )

    def test_max_megapixels_caps_large_crop_and_still_stitches(self):
        _, _, (uncapped, _, _, _) = self._crop_large_mask()
        self.assertEqual(uncapped.shape[1] * uncapped.shape[2], 1984 * 1984)

        image, mask, (crop_image, crop_mask, info, _) = self._crop_large_mask(max_megapixels=1.5)
        height, width = crop_image.shape[1:3]
        self.assertLessEqual(width * height, 1_500_000)
        self.assertEqual((width % 64, height % 64), (0, 0))
        self.assertEqual(info["target_w"], [width])

        result = SmartImageStitcher().stitch(image, crop_image, info, 0, blend_mode="Mask Feather", mask=crop_mask)[0]
        self.assertEqual(tuple(result.shape), tuple(image.shape))
        # The crop is the original pixels, so stitching it back straight changes little despite the downscale.
        self.assertLess(float((result - image).abs().mean()), 0.2)

    def test_max_megapixels_leaves_small_crops_alone(self):
        image = torch.rand(1, 512, 512, 3)
        mask = torch.zeros(1, 512, 512)
        mask[:, 240:260, 240:260] = 1.0
        crop_image = SmartImageCrop().run(
            image=image,
            mask=mask,
            resolution_mode="Automatic",
            max_resolution=2048,
            min_resolution=1024,
            manual_width=1024,
            manual_height=1024,
            mask_grow_pixels=0,
            patch_mask_holes=False,
            no_mask_mode="Bypass",
            force_divisibility=64,
            max_megapixels=2.0,
        )[0]
        self.assertEqual(tuple(crop_image.shape[1:3]), (1024, 1024))

    def test_large_image_preview_is_smaller_and_shows_the_crop(self):
        _, _, (_, _, _, overlay) = self._crop_large_mask()
        self.assertEqual(tuple(overlay.shape), (1, 1536, 2048, 3))
        # Green border and red tint land where the 4000 px image's crop and mask scale down to.
        self.assertGreater(float(overlay[0, 760, 1024:1100, 0].mean()), 0.0)
        border = overlay[0, 256:1280, :, 1] == 1.0
        self.assertTrue(bool(border.all(dim=0).any()))


if __name__ == "__main__":
    unittest.main()
