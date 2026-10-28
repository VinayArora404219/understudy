# Example inputs

Everything the demo feeds the app:

```
examples/
  clips/        six source clips: real stock footage from Pexels, with sound added
  characters/   six character photos (five people and an orange cat), generated with Qwen-Image
  prompts/      the prompt behind each character photo
```

A person recast in a stock clip is always replaced by one of the generated characters, never by a real
person's likeness.

The clip files are not kept in git (`*.mp4` is ignored), since the Pexels License doesn't allow re-hosting them.
`python3 tools/fetch_examples.py` rebuilds them from Pexels, checked against the hash of each clip we used.
Pixabay doesn't allow scripted downloads, so download the three music tracks below by hand first; without
them the clips are made without sound.
The measurements in [`bench/RESULTS.md`](../bench/RESULTS.md) were made earlier on private test clips
(Clips A–F there). Those clips are not ours to publish, so no frame of them appears in this repository
or in the demo.

## Clips

| Clip | What it tests | Source clip | Creator | Sound |
|---|---|---|---|---|
| `dance_trio.mp4` | Two of three dancers recast; the one between them stays as filmed | [People dancing](https://www.pexels.com/video/people-dancing-8811210/) (24 s) | [Yan Krukau](https://www.pexels.com/@yankrukov) | music |
| `street_sunglasses.mp4` | An action partway through (sunglasses taken off) lands on time | [A woman in a black dress taking her sunglasses off](https://www.pexels.com/video/a-woman-in-a-black-dress-taking-her-sunglasses-off-14955510/) (5 s) | [Connor Scott McManus](https://www.pexels.com/@connorscottmcmanus) | none |
| `dance_duo_studio.mp4` | Two dancers at once, white studio | [Two girls dancing and having fun](https://www.pexels.com/video/two-girls-dancing-and-having-fun-4820385/) (6 s) | [Polina Tankilevitch](https://www.pexels.com/@polina-tankilevitch) | music |
| `dance_ballet_balcony.mp4` | Fast high kicks and extensions on a narrow balcony | [A man dancing while holding on railings](https://www.pexels.com/video/a-man-dancing-while-holding-on-railings-8854001/) (17 s) | [Los Muertos Crew](https://www.pexels.com/@cristian-rojas) | music |
| `dance_breaking.mp4` | Breakdance: floor work, legs over the head, a hard test for pose tracking | [Young man practicing break dance](https://www.pexels.com/video/young-man-practicing-break-dance-5363330/) (6 s) | [Allan Mas](https://www.pexels.com/@allan-mas) | music |
| `dance_man_and_dog.mp4` | A man and his dog dancing together; the camera zooms and the dog leaves the frame at times | [A man in a blue shirt and pants is standing on a blue background](https://www.pexels.com/video/a-man-in-a-blue-shirt-and-pants-is-standing-on-a-blue-background-20186498/) (16 s) | [K](https://www.pexels.com/@kelly) | music |

The [Pexels License](https://www.pexels.com/license/) allows free use and modification. We follow its
conditions: nobody in these clips is shown in a bad light, nothing implies their endorsement, and the
original clips are linked above rather than copied here. The clips were chosen to show no logos or brand
names. The picture of each clip is unchanged; only sound was added.

### Sound

The Pexels clips come without sound, and Recast keeps a clip's own sound, so sound was laid under the
source clip before upload and carries through to the result.

| Track | Creator | Under |
|---|---|---|
| "Hip Hop Music" (Pixabay track 593670) | kiravale | `dance_duo_studio` from 0:12, `dance_breaking` from 0:39 |
| "Chill Hip Hop (Version 2)" (Pixabay track 544088) | BombinSound | `dance_ballet_balcony` from 0:24, `dance_man_and_dog` from 0:44 |
| "Hip Hop Beat" (Pixabay track 607791) | lnplusmusic | `dance_trio` from 0:28 |

All three are from [Pixabay](https://pixabay.com/music/) under the
[Pixabay Content License](https://pixabay.com/service/license-summary/), which allows free use and
modification without attribution; we credit the creators anyway. Each track is cut from the time shown
(a point where the beat is already going), levelled to −14 LUFS, faded in over 0.3 s and out over 0.8 s. The tracks are not redistributed on their own.

## Characters

| Photo | Prompt | Seed |
|---|---|---:|
| `chef.png` | [`char_chef.txt`](prompts/char_chef.txt) | 1 |
| `raincoat.png` | [`char_raincoat.txt`](prompts/char_raincoat.txt) | 1 |
| `grandpa.png` | [`char_grandpa.txt`](prompts/char_grandpa.txt) | 1 |
| `runner.png` | [`char_runner.txt`](prompts/char_runner.txt) | 2 |
| `astronaut.png` | [`char_astronaut.txt`](prompts/char_astronaut.txt) | 2 |
| `cat.png` | [`char_cat.txt`](prompts/char_cat.txt) | 1 |

Made with [Qwen-Image](https://huggingface.co/Qwen/Qwen-Image) text-to-image (Apache-2.0; Q4_K_M GGUF,
text encoder [Qwen2.5-VL-7B-Instruct](https://huggingface.co/Qwen/Qwen2.5-VL-7B-Instruct), Apache-2.0)
in ComfyUI: 20 steps, cfg 4, 864×1536, seeds 1, 2 and 3, best of the three picked by eye. In each prompt
file, the first paragraph is the prompt and the `NEG:` line is the negative prompt. Qwen-Image only made
these photos; the app itself runs the models listed in [`manifests/models.json`](../manifests/models.json).

The prompts follow what earlier tests taught us:

- **Alone on a plain grey backdrop, nothing beside them.** An object next to a character in their photo
  (a helmet on a desk) was carried into the render in place of what the performer did.
- **The face is described in words**: heritage, face shape, build, hair, skin. With Qwen-Image the
  identity follows the words; a different seed with the same words gives the same kind of face. Skin-tone
  words alone were ignored (four of five characters first came back with the same face type); naming
  each character's heritage fixed it.
- **No logos, text or badges**, and only things the character wears. Nothing is held in the hands.
  (Seed 3 of the astronaut drew a flag patch on the sleeve, so seed 2 was kept.)
- **Facing the camera.** Head-and-shoulders crops for another place need a findable face.

## Labelling

- In the demo video, every result carries the label "AI-generated", and each source clip is credited to
  its Pexels creator.
- Visitors who upload their own clips confirm they have the consent of everyone on camera (see the app's
  upload step).
