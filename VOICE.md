# Voice

* The various models like `microsoft/VibeVoice-ASR`, `Qwen/Qwen3-TTS`, etc have corresponding GitHub repos with PyTorch programs to load the model and do their thing.
* These will basically have different python packages to each other.
  * Use venvs to keep everything isolated, otherwise they'll break each other.
  * Follow guide below to ensure right ROCm PyTorch and flash attention 2 etc are installed.

## Tmux Trick
* XXX TODO move somewhere else.
* `tmux pipe-pane -t podman:16.0 -O notify` - pipes new stdout of the pane into the command specified (projectdiscovery/notify) so it will send me a slack message - can go AFK and get notified when there's new output - e.g long running command has finished or gotten an error.
* `tmux pipe-pane -t podman:16.0` - stop monitoring pane output


## Voice Tasks
* STT - Speech to Text
* TTS - Text to Speech
* VAD - Voice Activity Detection
* ASR - Automatic Speech Recognition
* Speaker Segmentation - is a weaker version of diarization, splitting into speaker turns but doesn't understand which speaker is which, if there's three speakers it will just say `[SPEAKER TURN]`, you will know speakers changed but not to which one.
This is what [akashmjn/tinydiarize](https://github.com/akashmjn/tinydiarize) can do.
* Speaker Diarization - is the process of partitioning an audio stream containing human speech into homogeneous segments according to the identity of each speaker.
  * This is better than segmentation, it knows which speaker is speaking (e.g. speaker 1, 2, 1, 3).
  * Use `microsoft/VibeVoice-ASR` for this

## Terminology
* RTF - Real-time Factor - lower if faster, 1.0 is equal, e.g. 1s to process 1s of audio. 0.5 RTF is 0.5s to process 1s of audio, e.g. its twice as fast as the real-time.
* RTFx - Inverse Real-time Factor - higher is faster, 1.0 is equal (1s to process 1s of audio), 2.0 is twice real-time, e.g  it can process 2s of audio in 1s wall clock time.
* Gradio - a popular software for making UIs for GenAI, often used for demos.

## Models

* whisper.cpp GGML models
  * VAD model
* Kokoro TTS
  * FastAPI docker container
* `microsoft/VibeVoice`
  * Two versions, an old one (TTS) and a new one (ASR)
* `Qwen2.5-Omni-7B`
  * Can do any to any modality, e.g a mix of text/audio/image/video in and text/audio/video out.
* `Qwen/Qwen3-TTS-12Hz-1.7B-Base`
  * Voice Cloning
* `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`
  * Voice Design - Give it what to say and also how to say it, e.g. "teenager that's anxious".
  * Not as good as Base for voice cloning.

## `microsoft/VibeVoice`
* This model got abused, and Microsoft deleted it.
  Both from huggingface and GitHub.
  * There's copies of it though, e.g. `aoi-ot/VibeVoice-Large`, and forks of the corresponding original GitHub code, e.g. https://github.com/kyuz0/VibeVoice[kyuz0/VibeVoice]
* This was originally TTS.
* Then microsoft released the `microsot/VibeVoice-ASR` and used the same github `microsoft/VibeVoice` but with a new git tree.
* kyuz0 had forked `microsoft/VibeVoice` before microsoft deleted it, so his tree and the new tree are wildly different.

### Old TTS model
* The old model is TTS focused.
* Deleted from HuggingFace and GitHub
* Forked though
* Demo is for old version of Gradio
  * I modified code to make it work with newer gradio (commented out arguments that don't exist anymore)
* Demo generates podcasts with multiple voices
* Needs `ffmpeg` installed will crash without it

### New ASR Model
* The new model is ASR focused.
* Re-used same GitHub repo, git tree is different.
* Slow
* This does speaker diarization
  * When, Who, What
* It is pretty slow on my Strix Halo, slower than realtime, RTFx is less than 1.
  * This is because it generates each frame and subsequent frames depend on the previous frame, so it can't "use more cores to process in parallel", it's serial.
  GPU utilisation for me is 5-15% as it progresses, GTT usage slowly creeps as it processes more frames.

## `Qwen/Qwen3-TTS`
* `examples/` I fixed the loading of the model by removing the trailing slash.

## Runtimes
* llama.cpp is designed to run specific model architectures and basically can't run any voice (e.g. TTS or SST, etc) models.
  * For performance the architectures are hard-coded, but this limits what models it's compatible with.
  * This can run `Qwen2.5-Omni-7B-GGUF`, but it has limited features of the model and doesn't support all the modalities in and out.
    Hopefully, over time this will get better.
* Whisper.cpp is designed to run OpenAI derived whisper models with GGUF file formats.
  * whisper.cpp can run `ggml-large-v3-turbo-q5_0.bin` etc models.
  * It can run Voice Activity Detection (VAD) models, e.g. `silero-v6.2.0`, which you should run.
  * The whisper models don't do as good VAD as the dedicated VAD models.
  * Running with a VAD, will be both more performant and better quality.
  * Running "naked" without a VAD will mean noise is sent to the STT model and it can hallucinate words etc.
* The architecture of the model is hard-coded so you can't run models like Qwen2.5-Omni etc

## Toolbox / Distroboxes

* These are basically docker images

### Good
* The https://github.com/kyuz0/amd-strix-halo-llm-finetuning[kyuz0/amd-strix-halo-llm-finetuning] Distrobox uses a venv in /opt/venv that is Python3.13
  * Docker Image: docker.io/kyuz0/amd-strix-halo-llm-finetuning:latest

```
% distrobox enter strix-halo-llm-finetuning


███████╗████████╗██████╗ ██╗██╗  ██╗      ██╗  ██╗ █████╗ ██╗      ██████╗
██╔════╝╚══██╔══╝██╔══██╗██║╚██╗██╔╝      ██║  ██║██╔══██╗██║     ██╔═══██╗
███████╗   ██║   ██████╔╝██║ ╚███╔╝       ███████║███████║██║     ██║   ██║
╚════██║   ██║   ██╔══██╗██║ ██╔██╗       ██╔══██║██╔══██║██║     ██║   ██║
███████║   ██║   ██║  ██║██║██╔╝ ██╗      ██║  ██║██║  ██║███████╗╚██████╔╝
╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝      ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝

                        L L M   F I N E - T U N I N G


AMD STRIX HALO — LLM Finetuning (gfx1151, ROCm via TheRock)
ROCm nightly: 7.12.0a20260203

Machine: Framework Desktop (AMD Ryzen AI Max 300 Series)
GPU    : AMD RYZEN AI MAX+ 395 w/ Radeon 8060S

Repo   : https://github.com/kyuz0/amd-strix-halo-llm-finetuning
Image  : docker.io/kyuz0/amd-strix-halo-llm-finetuning:latest

Quickstart:
  - 1. Copy notebooks to home directory → mkdir -p ~/finetuning-workspace; cp -r /opt/workspace/* ~/finetuning-workspace/
  - 2. Start Jupyter Lab → jupyter lab --notebook-dir ~/finetuning-workspace/
```

* Much newer ROCm nightly: `7.12.0a20260203`
* I got Qwen2.5-Omni, VibeVoice (old), VibeVoice (new, ASR), working in this.

#### Fix triton stuff
* When entering the distrobox the shell scripts in `/etc/profile.d/` will run, in lexical order.
* `/etc/profile.d/01-rocm-env-for-triton.sh` will run first, but the venv hasn't been entered yet, and `_rocm_sdk_core` module can't be found in the system's python site-packages - this is python 3.14.
* Solution, `sudo mv /etc/profile.d/venv.sh /etc/profile.d/00-venv.sh`.
  * This ensures the venv is entered first, now the rocm SDK can be found, and the triton env vars will be set.


### Bad - outdated
* https://github.com/kyuz0/amd-strix-halo-voice-toolbox

```
% distrobox enter  strix-halo-voice

███████╗████████╗██████╗ ██╗██╗  ██╗      ██╗  ██╗ █████╗ ██╗      ██████╗
██╔════╝╚══██╔══╝██╔══██╗██║╚██╗██╔╝      ██║  ██║██╔══██╗██║     ██╔═══██╗
███████╗   ██║   ██████╔╝██║ ╚███╔╝       ███████║███████║██║     ██║   ██║
╚════██║   ██║   ██╔══██╗██║ ██╔██╗       ██╔══██║██╔══██║██║     ██║   ██║
███████║   ██║   ██║  ██║██║██╔╝ ██╗      ██║  ██║██║  ██║███████╗╚██████╔╝
╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝      ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝ ╚═════╝

                                V O I C E

STRIX HALO — Voice Toolbox (gfx1151, ROCm)
ROCm nightly: 7.0.0rc20250903

Machine: Framework Desktop (AMD Ryzen AI Max 300 Series)
GPU    : AMD RYZEN AI MAX+ 395 w/ Radeon 8060S

Image  : docker.io/kyuz0/amd-strix-halo-voice:latest

Usage:
  - VibeVoice (Gradio)       → vibevoice --model_path ~/VibeVoice-Large --port 8000
```

* Note the outdated ROCm nightly: `7.0.0rc20250903`
* Other things also outdated.
* New things don't work.
* Avoid, use the finetuning one instead.


## Running different python programs
## Python Install
* The tools etc aren't compatible with Python 3.14 yet
* From the default venv (`/opt/venv/`) that is automatically activated when entering the distrobox, use `python -m venv venv` to create a new venv for each git repo.
  * This will use Python3.13.

* install `uv` via `sudo dnf install uv`, then running it, it crashes segv for me, so just use `pip` (in a venv).


### Install PyTorch ROCm version

* Based off the kyuz0/amd-strix-halo-llm-finetuning Dockerfile

```bash
python -m pip install \
    --index-url https://rocm.nightlies.amd.com/v2-staging/gfx1151/ \
    --pre torch torchaudio torchvision
```


### Install flash attention 2

#### Check flash attention 2 is working


```bash
python -c "import flash_attn; print(flash_attn.__version__, flash_attn.__file__)"
```

Not working:

```
Traceback (most recent call last):
  File "<string>", line 1, in <module>
    import flash_attn; print(flash_attn.__version__, flash_attn.__file__)
    ^^^^^^^^^^^^^^^^^
ModuleNotFoundError: No module named 'flash_attn'
```

* Probably because it's not installed.

Working:

```
2.8.3 /home/bdawg/co/git/Qwen3-TTS/venv/lib64/python3.13/site-packages/flash_attn/__init__.py
```

* After installing it, this is what you should see.


<!-- vim: set spell: -->
