import argparse
import os

import torch
import torchaudio

from api import TextToSpeech, MODELS_DIR
from utils.audio import load_voices
from utils.text import split_and_recombine_text

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--text', type=str, help='Text to speak.', default="The expressiveness of autoregressive transformers is literally nuts! I absolutely adore them.")
    parser.add_argument('--voice', type=str, help='Selects the voice to use for generation. See options in voices/ directory (and add your own!) '
                                                 'Use the & character to join two voices together. Use a comma to perform inference on multiple voices.', default='random')
    parser.add_argument('--preset', type=str, help='Which voice preset to use.', default='fast')
    parser.add_argument('--use_deepspeed', type=str, help='Use deepspeed for speed bump.', default=False)
    parser.add_argument('--kv_cache', type=bool, help='If you disable this please wait for a long a time to get the output', default=True)
    parser.add_argument('--half', type=bool, help="float16(half) precision inference if True it's faster and take less vram and ram", default=True)
    parser.add_argument('--output_path', type=str, help='Where to store outputs.', default='results/')
    parser.add_argument('--model_dir', type=str, help='Where to find pretrained model checkpoints. Tortoise automatically downloads these to .models, so this'
                                                      'should only be specified if you have custom checkpoints.', default=MODELS_DIR)
    parser.add_argument('--candidates', type=int, help='How many output candidates to produce per-voice.', default=3)
    parser.add_argument('--seed', type=int, help='Random seed which can be used to reproduce results.', default=None)
    parser.add_argument('--produce_debug_state', type=bool, help='Whether or not to produce debug_state.pth, which can aid in reproducing problems. Defaults to true.', default=True)
    parser.add_argument('--cvvp_amount', type=float, help='How much the CVVP model should influence the output.'
                                                          'Increasing this can in some cases reduce the likelihood of multiple speakers. Defaults to 0 (disabled)', default=.0)
    args = parser.parse_args()
    if torch.backends.mps.is_available():
        args.use_deepspeed = False
    os.makedirs(args.output_path, exist_ok=True)
    tts = TextToSpeech(models_dir=args.model_dir, use_deepspeed=args.use_deepspeed, kv_cache=args.kv_cache, half=args.half)

    if '|' in args.text:
        print("Found the '|' character in your text, which I will use as a cue for where to split it up. If this was not" \
              " your intent, please remove all '|' characters from the input.")
        texts = args.text.split('|')
    else:
        texts = split_and_recombine_text(args.text)

    selected_voices = args.voice.split(',')
    for k, selected_voice in enumerate(selected_voices):
        if '&' in selected_voice:
            voice_sel = selected_voice.split('&')
        else:
            voice_sel = [selected_voice]
        voice_samples, conditioning_latents = load_voices(voice_sel)

        candidate_parts = [[] for _ in range(args.candidates)]
        dbg_states = []
        for text in texts:
            gen, dbg_state = tts.tts_with_preset(text, k=args.candidates, voice_samples=voice_samples,
                                  conditioning_latents=conditioning_latents,
                                  preset=args.preset, use_deterministic_seed=args.seed,
                                  return_deterministic_state=True, cvvp_amount=args.cvvp_amount)
            dbg_states.append(dbg_state)
            if isinstance(gen, list):
                for j, g in enumerate(gen):
                    candidate_parts[j].append(g.squeeze(0).cpu())
            else:
                candidate_parts[0].append(gen.squeeze(0).cpu())

        for j, parts in enumerate(candidate_parts):
            audio = torch.cat(parts, dim=-1)
            suffix = f'_{k}_{j}' if args.candidates > 1 else f'_{k}'
            torchaudio.save(os.path.join(args.output_path, f'{selected_voice}{suffix}.wav'), audio, 24000)

        if args.produce_debug_state:
            os.makedirs('debug_states', exist_ok=True)
            torch.save(dbg_states, f'debug_states/do_tts_debug_{selected_voice}.pth')

