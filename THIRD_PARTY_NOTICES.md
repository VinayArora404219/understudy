# Third-party notices

Performance Recast's own code is MIT (see [LICENSE](LICENSE)). It ships no model weights and no ComfyUI code:
the models are downloaded from their publishers at the pinned revisions below, and ComfyUI runs as a separate
program that the app talks to over HTTP through the Comfy SDK. The full list with sizes and SHA-256 hashes is
[manifests/models.json](manifests/models.json).

## Models

| File | Used by | Licence | Source |
|---|---|---|---|
| `wan_animate_2_distill_int8_convrot.safetensors` | recast CLI (recast/graph.py, Wan-Animate-2); the app uses SCAIL-2 | Apache-2.0 | Comfy-Org/Wan-Animate-2 |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | Recast and Restyle text encoder (scail.py, vace.py, graph.py) | Apache-2.0 | Comfy-Org/Wan-Animate-2 |
| `clip_vision_h.safetensors` | Recast (scail.py, graph.py) | MIT | Comfy-Org/Wan-Animate-2 |
| `wan_2.1_vae.safetensors` | Recast and Restyle VAE (scail.py, vace.py, graph.py) | Apache-2.0 | Comfy-Org/Wan-2.1 |
| `qwen-image-edit-2511-Q4_K_M.gguf` | reference matching (reference.py) | Apache-2.0 | unsloth/Qwen-Image-Edit-2511-GGUF |
| `qwen_2.5_vl_7b_fp8_scaled.safetensors` | reference matching | Apache-2.0 | Comfy-Org/Qwen-Image |
| `qwen_image_vae.safetensors` | reference matching | Apache-2.0 | Comfy-Org/Qwen-Image |
| `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors` | reference matching (quality=fast) | Apache-2.0 | lightx2v/Qwen-Image-Edit-2511-Lightning |
| `face_detection_full_range_sparse.tflite (bundled in the mediapipe wheel)` | character head-and-shoulders crop (recast/crop.py) | Apache-2.0 | https://pypi.org/project/mediapipe/0.10.21/ |
| `qwen3vl_8b_int8_convrot.safetensors` | first-frame description: performers and their poses (recast/describe.py) | Apache-2.0 (Comfy-Org/Qwen3-VL repack of Qwen3-VL-8B-Instruct; the same bytes are also in Comfy-Org/Qwen-Image-2.1, but that repo is under the non-commercial Qwen Research licence, so take it from here) | Comfy-Org/Qwen3-VL |
| `birefnet.safetensors` | cut-out of character, outfit and product images before the edit (recast/reference.py) | MIT | Comfy-Org/BiRefNet |
| `SCAIL-2-Q4_K_M.gguf` | Recast video model, both places (recast/scail.py) | MIT | realrebelai/SCAIL-2_GGUF |
| `wan2.1_SCAIL_2_DPO_lora_bf16.safetensors` | Recast (recast/scail.py) | MIT | Comfy-Org/SCAIL-2 |
| `sam3.1_multiplex_fp16.safetensors` | tracking the clip's performers and the characters for Recast (recast/scail.py) | SAM License (Meta, custom): commercial use allowed; conditions are trade-control compliance, no military/weapons use, ship the licence text with any redistribution, acknowledge SAM in publications | Comfy-Org/sam3.1 |
| `Wan2.1_14B_VACE-Q4_K_S.gguf` | Restyle, video to video (recast/vace.py) | Apache-2.0 | QuantStack/Wan2.1_14B_VACE-GGUF |
| `Wan21_T2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors` | Restyle speed-up (recast/vace.py); replaces CausVid, which is CC-BY-NC-4.0 | Apache-2.0 | lightx2v/Wan2.1-T2V-14B-StepDistill-CfgDistill-Lightx2v |
| `lightx2v_I2V_14B_480p_cfg_step_distill_rank64_bf16.safetensors` | Recast speed-up (recast/scail.py) | Apache-2.0 (inherited from the lightx2v upstream; the Kijai/WanVideo_comfy repo that hosts this re-save states no licence of its own) | Kijai/WanVideo_comfy |
| `depth_anything_v2_vits.pth` | Restyle control video (recast/vace.py); the node downloads it on first use, so place it in images | Apache-2.0 (Small only; Base/Large are CC-BY-NC-4.0) | depth-anything/Depth-Anything-V2-Small |

Every model above allows commercial use. Two have conditions worth reading: SAM 3.1 is under Meta's SAM
License (trade-control compliance; no military or weapons use), and only the Small Depth Anything V2 model is
Apache-2.0 (Base and Large are CC-BY-NC-4.0, so they are not used).

## ComfyUI and custom nodes (run as separate programs, not included here)

| Component | Version | Licence | Repository |
|---|---|---|---|
| ComfyUI | 0.41.3 (`8713616fcc32`) | GPL-3.0 | https://github.com/comfyanonymous/ComfyUI |
| comfyui-videohelpersuite | 1.7.9 | GPL-3.0 | https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite |
| ComfyUI-GGUF | 1.1.10 | Apache-2.0 | https://github.com/city96/ComfyUI-GGUF |
| comfyui_controlnet_aux | 1.1.5 | Apache-2.0 | https://github.com/Fannovel16/comfyui_controlnet_aux |

## Libraries

| Library | Licence |
|---|---|
| comfy-sdk | MIT |
| comfy-api-proxy (on the GPU host) | MIT |
| FastAPI | MIT |
| Uvicorn | BSD-3-Clause |
| MediaPipe (and its bundled face detection model) | Apache-2.0 |
| OpenCV | Apache-2.0 |
| NumPy, SciPy | BSD-3-Clause |
| Pillow | MIT-CMU |
| python-multipart | Apache-2.0 |
| React, React Router, TanStack Query | MIT |
| Tailwind CSS, Vite | MIT |
