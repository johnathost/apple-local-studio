# Master Lora

### SNOFS (Sex, Nudes, Other Fun Stuff)

Description:

```plaintext
Want to support my work or help fund the training of this dataset on other models? Join the Patreon in my profile, and if you do - thank you!
Krea 2 V1.3D:

Alright, alright. I figured out a way to greatly restore texture back. It wasn't more training or different settings, and that's all I'm going to say about it. I deserve to have some trade secrets, no? I made it version 1.3D because the D stands for detail. It was actually try F, as in I was totally...frustrated...with how many lengthy tries it took.

Anyways, I had versions that took it further but it tended to have more broken anatomy. So, the same rules still apply if you want something to look like a photo:

Be sure to mention that it's a photo/photograph in the prompt. Do NOT use "photorealistic" or any other term that doesn't actually mean a photo. Krea 2 was trained on a ton of artwork so using any of those types of terms will yeet it back to bad texture.

Some rare prompts might still want to go over to the anime-side, but I still have the photo slider directly on SNOFS Krea. Simply set it to somewhere around .5-2 on the strength and you're probably golden. This was trained on SNOFS 1.2 so I'll be putting out an updated version at some point:
https://civitai.red/models/2823820/photodetail-slider-for-snofs-krea

The same goes for some specific terms. When in doubt, use the words listed below instead of their synonyms.

My two-stage sampler is still handy for multiple reasons:
https://github.com/Auryg/Krea-2-Two-Stage-Sampler

The idea for the two-stage sampler that you can generate without the turbo lora for the first bit, which helps with variation and prompt adherence, and then bump to a second stage with the turbo lora to keep things fast. For the three-stage variation, you can then bump back to doing it without the turbo lora for the last bit if you want to use a negative prompt. You can also generate at a lower resolution to start and then bump it up.

Also, please, for the love of god try SNOFS by itself before you go adding a bunch of other general NSFW loras or models to it that screw up anatomy.
Ideogram:

Ideogram model has been updated, and is available here: https://civitai.red/models/2781404/sex-nudes-other-fun-stuff-ideogram-snofs
General Information:

SNOFS was trained on natural language (or JSON, for Ideogram), not tags. It will work best if you use full sentences to describe what you want.

Not using ComfyUI/your inference software doesn't support lokr? I've put up a merged version here. You can also use the merged base model to train off of: https://civitai.red/models/2416142/snofs-sex-nudes-and-other-fun-stuff-flux-2-klein-9b-base-and-distilled

Here's a list of some of the terms that work well:

    anus

    blowjob

    boudoir

    condoms

    deepthroat

    braless

    cowgirl position

    cum

    cunnilingus (be specific and maybe put kissing in the negative prompt)

    deepthroat

    dildo

    doggystyle position

    fingering (anal and vaginal)

    hand in panties

    handjob

    hitachi magic wand

    implied blowjob

    ipcam / nightvision ipcam

    masturbating (might want to put penis in negative prompt, or specify what she's rubbing for women)

    massage

    missionary position

    naked, nude, etc.

    penis

    pregnant (and can specify trimester)

    prone position

    reverse cowgirl position

    sex

    sheer

    snapchat (and caption/text/etc)

    selfie (and mirror selfie)

    spooning position

    strap-on dildo

    tentacles

    licking testicles

    undressing

    vagina

    wet clothes

Depending on the version, the following might work:

    anal sex

    anilingus

But also keep in mind that it was trained on stuff like "her panties are pulled down to her thighs," not "panty pull."

These models are under the following license:

https://huggingface.co/Ashen3/SNOFS

Flux 2 Klein 9b V1.4:

Additional training. Some of the training was done using https://github.com/BuffaloBuffaloBuffaloBuffalo/ai-toolkit-perceptual , training against depth. Considering how much of SNOFS is two people intermingled with close skin colors, it seemed like a novel idea. It did seem to rapidly help with that sort of thing. On the downside, it seemed to create a bit of a texture issue on very close up images. I did some more training after to try to bring that back and was somewhat successful, but I think I'd need to increase the weight decay to really make that happen. Since everything else was in a good state I decided to release as-is. If you do have that texture issue, try adding "goosebumps" as a negative prompt.
```

# Other Lora Models

#### Huge Gape - Vaginal | For Flux 2.0 Klein 9B
- URL: https://civitai.red/models/2437614/huge-gape-vaginal-or-for-flux-20-klein-9b
- Filename: ``HugeGape_Vagina_Light_v2.safetensors``

Trigger Words:
```text
she has a gaping pussy,
she is gaping her pussy,
she is spreading her pussy,
```

Example Prompts:
```text
"legs spread wide with knees bent and feet resting on a bed, torso leaning forward, one hand spreading her vagina open, genital area fully exposed including the mons pubis and a detailed view of the labia and vaginal opening which is wet with lubrication"
```
```text
"prominent visibility of the mons pubis with dark hair, labia majora and minora, vaginal opening and internal vaginal canal"
```

#### Missionary POV Vaginal (Flux 2 klein 9b)
- URL: https://civitai.red/models/2465199/missionary-pov-vaginal-flux-2-klein-9b
- Filename: ``FK_missionary.safetensors``

Trigger Words:
```text
missionary, vaginal sex, vaginal penetration, pov, girl in the image is lying on her back, spreading her legs. a man is penetrating her pussy. she has vaginal sex with the man in missionary position. she is looking at the camera. the man is out of frame.
```

#### Cum On Face (Klein 9b, SDXL)
- URL: https://civitai.red/models/146522/cum-on-face-klein-9b-sdxl
- Filename: ``cum_on_face_v2.safetensors``

Trigger Words:
```text
cum on her face, semen on her face,
```

#### Huge Gape - Anal | For Flux 2.0 Klein 9B
- URL: https://civitai.red/models/2434792/huge-gape-anal-or-for-flux-20-klein-9b
- Filename: ``HugeGape_Anal_V3_AIO.safetensors``

Trigger Words:
```text
anal gape
she has a gaping ass
huge gape
```

#### POV Anal LoRA - Flux.2 Klein 9B - K3NK
- URL: https://civitai.red/models/2435368/pov-anal-lora-flux2-klein-9b-k3nk
- Filename: ``klein-pov-anal-11epoc-k3nk.safetensors``

Trigger Words:
```text
a woman riding a man's penis while facing away from the camera. The woman's large, round buttocks are prominently displayed.
```

#### Doggystyle anal Spitroast (ass focus) (flux 2 klein 9b)
- URL: https://civitai.red/models/2512133/doggystyle-anal-spitroast-ass-focus-flux-2-klein-9b
- Filename: ``FK_spitroastanal.safetensors``

Trigger Words:
```text
(from side): in the image is the woman and two men. the girl is positioned on all fours and performs oral sex on one of the men. the other man is penetrating her anus from behind. threesome sex with one woman and two men. doggystyle spitroast sex. anal sex, oral sex and deepthroat.
```
```text
the photograph depicts an explicit, adult scene involving three individuals. The central focus is on the woman who is positioned on all fours on a ottoman. She is exposing her buttocks and genitals. She performs oral sex on a man with a large, erect penis. she is also being penetrated from behind by another  man, whose erect penis is visible entering her anus. the men's torsos and lower bodies are visible, while their faces are out of frame. keep her outfit and her hair style.
```
```text
(ass focused working on portrait  format): the image shows the woman and two men. the girl is positioned on all fours and performs oral sex on one of the men. the other man is penetrating her anus from behind. Threesome sex with one woman and two men. Doggystyle spitroast sex. anal sex, oral sex and deepthroat. The central focus is on the woman, positioned on a bench/bed/ottoman... She is on all fours, with her back arched and head turned to the right. The woman is engaged in oral sex with a nude man on the right, whose erect penis is in her mouth. the men's bodies are visible, while their faces are out of frame. At the same time, another nude man is penetrating her anus from behind. His penis is visible, entering her anus. camera is focused on her anus and her buttocks are prominently displayed. the girls body is turned away from the camera.
```
```text
keep her outfit and hair style and the setting.
```

#### Prolapse - Anal | For Flux 2.0 Klein 9B
- URL: https://civitai.red/models/2446009/prolapse-anal-or-for-flux-20-klein-9b
- Filename: ``MrWeaz_ProlapseAnus_v2.safetensors``

Trigger Words:
```text
AN4LPR0L4PS3, a woman, she has a prolapsed anus, anal prolapse, rosebud,
```

#### Self Fisting - Anal | For Flux Klein 9B
- URL: https://civitai.red/models/2440638/self-fisting-anal-or-for-flux-klein-9b
- Filename: ``SelfFisting_Anal_v1.safetensors``

Trigger Words:
```text
self anal fisting,
she is self fisting her ass,
she has her hand in her ass,
she is fisting her own ass,
```

#### Cowgirl anal sex (Flux 2 klein 9b)
- URL: https://civitai.red/models/2523236/cowgirl-anal-sex-flux-2-klein-9b
- Filename: ``FK_bbcanalcowgirl_epoch_20.safetensors``

Trigger Words:
```text
you can probably add a bit of angles and stuff... Trainingsdata is only from behind.
```
```text
image shows one girl and one man. the girls is sitting on the mans lap. her ass is turned to the viewer. the face is only partially visible, because she is turned with the back to the viewer.  she is looking back at the camera. the penis of the man is penetrating her anus. focus of the image is the anal sex scene. the penis and testicles and legs of the man are visible. his the view of his upper body is mostly blocked by the girls back.   the photograph depicts an explicit sexual scene between a white woman and a black man. she is positioned on top of the man, facing away from the camera, with her buttocks prominently displayed. the man, is lying on a couch. his erect, large penis is visibly penetrating her anus from behind.
```

#### extreme Sloppy / messy deepthroat (Flux 2 Klein 9b, SDXL)
- URL: https://civitai.red/models/2244773/extreme-sloppy-messy-deepthroat-flux-2-klein-9b-sdxl
- Filename: ``FK_sloppydeepthroat_epoch_10.safetensors``

Trigger Words:
```text
d33p, woman in the image is deepthroating and sucking a big penis of a man next to her. saliva ist drooling from her mouth. there are cum strings and saliva strings. with spit bubbles.add the the penis, lower body, thighs and testicles of a man next to her.
```

#### mounted / Lying Facehumping / implied facefuck (Flux 2 klein 9b)
- URL: https://civitai.red/models/2479519/mounted-lying-facehumping-implied-facefuck-flux-2-klein-9b
- Filename: ``FK_facehumping.safetensors``

Trigger Words:
```text
image shows the girl lying on her back and a naked man straddling on her face. the upper body of the man is out of frame and his testicles are covering the girls face. the face of the girl is covered by the man. the image is shot from below. the image shows an implied fellatio. the girl is grabbing the mans thighs. the girl, is lying on her back on a bed with white sheets. he man's lower body is the only part of him visible in the frame, with his legs and buttocks in the upper part of the image.

keep the outfit of the girl,

her thong is pulled aside and her vagina is exposed. The girls thong is partially pulled down, and her pubic area is prominently displayed.

there is cum in her pussy. cum is flowing out of her pussy.

add cum to XYZ

the girl wears ... (to keep outfit consistent)
```

#### Cum Anywhere Concept
- URL: https://civitai.red/models/2473823/cum-anywhere-concept
- Filename: ``Cum_on_Face.safetensors``

Trigger Words:
```text
semen
cum
semen or cum location
semen or cum amount
after blowjob
after handjob
```

#### Femboys, Tgirls, and Futa
- URL: https://civitai.red/models/2536918/femboys-tgirls-and-futa
- Filename: ``femboy_lora_v5_LoKr16_000030000.safetensors``

Trigger Words:
```text
femboy
tgirl
```

#### Futanari Penis (Flux.2 Klein 9B)
- URL: https://civitai.red/models/2324280/futanari-penis-flux2-klein-9b
- Filename: ``Flux2_Klein_9B_Futanari_Penis_(Degenerator123).safetensors``

Trigger Words:
```text
woman with a penis
see description
```

#### NippleDiffusion - Flux2.Klein
- URL: https://civitai.red/models/2331032/nipplediffusion-flux2klein
- Filename: ``nipplediffusion-f2-klein-9b_v3.safetensors``

Trigger Words:
```text
naked breasts
nude tits
```

#### Pov Blowjob Klein 9B
- URL: https://civitai.red/models/2331924/pov-blowjob-klein-9b
- Filename: ``POV_blowjobV1_A.safetensors``

Trigger Words:
```text
pov photo of a latina girl with red lips she wears the Headband of image , doing a blowjob , pov from man view, the light is coming from a window. she is in a pink room, candid photo.
```

#### The Body [Flux.2.klein.9B]
- URL: https://civitai.red/models/2318875/the-body-flux2klein9b
- Filename: ``The_Body_Version_A_Flux2.k.9B_r16_AdamW8Bit_Weighted_768_woman_000005000.safetensors``

Trigger Words:
```text
woman
```

#### Dildo Riding
- URL: https://civitai.red/models/2409435/dildo-riding
- Filename: ``Dildo riding.safetensors``

Trigger Words:
```text

```

#### Nude legs spreading - Klein 9B
- URL: https://civitai.red/models/2322539/nude-legs-spreading-klein-9b
- Filename: ``spread_legs_beta1.safetensors``

Trigger Words:
```text
a woman spreading legs
```

#### Breast Implants
- URL: https://civitai.red/models/2379205/breast-implants
- Filename: ``Breast_Implanter_v5.0_exp.safetensors``

Trigger Words:
```text
Size: small, medium, large, huge, gigantic, massive, etc.
Shape: round, perky, "bolted on" (these aren't as good as I wanted them to be)
General Modifiers: very, extremely, significant, prominent, etc.
Other: busty, bust, bustline, voluptuous, curvy, etc.

A medium shot of a girl with [size] breast(s) (implants) facing to the right. She is wearing [a tight, thin shirt] and [smiling]. Her breasts are [very perky] and [round]. The outline of her nipples peaks are visible.... [rest of prompt]
```

#### TittyFuck LoRA - Flux.2 Klein 9B - K3NK
- URL: https://civitai.red/models/2442762/tittyfuck-lora-flux2-klein-9b-k3nk
- Filename: ``klein-tittyfuck-11epoc-k3nk.safetensors``

Trigger Words:
```text
a woman kneels with her hands squeezing her large breasts, she is looking at the viewer, she rests her breasts on a man's crotch, a man's naked lower body is seen near the bottom of the frame, his penis is seen disappearing in her cleavage, his crotch and her breasts are joined. highly detailed, 8k crisp details, sharp focus

a fair-skinned woman, nude, kneeling in front of a man's large penis. She has gigantic sized breasts and is holding the man's large, erect penis is positioned in between her breasts with her hands. The camera angle is from above, capturing her from the chest up.
```

#### Trans femboy | [Klein 9B, Qwen]
- URL: https://civitai.red/models/1899877/trans-femboy-or-klein-9b-qwen
- Filename: ``femboy_krea2.safetensors``

Trigger Words:
```text
androgynous femboy
```

#### Self Fisting - Vaginal | For Flux Klein 9B
- URL: https://civitai.red/models/2440823/self-fisting-vaginal-or-for-flux-klein-9b
- Filename: ``SelfFisting_Vaginal_v1.safetensors``

Trigger Words:
```text
she is self fisting her vagina
she is fisting her own vagina
she has her hand in her vagina
self fisting
her {left|right} hand is inserted into her vagina
```

#### SexGod Female Masturbation - Flux Klein 9b Lora
- URL: https://civitai.red/models/2441420/sexgod-female-masturbation-flux-klein-9b-lora
- Filename: ``SEXGOD_FemaleMasturbation_Klein9b_v1.safetensors``

Trigger Words:
```text
MASTURBATE
```

#### POV Blowjob

- URL: https://civitai.red/models/2514609/pov-blowjob
- Filename: ``pov_blowjob_krea2_v1.safetensors``
- Strength: 1

Trigger Words:
```text
Basic Prompt: Highly explicit, high-angle, close-up photo of a nude woman. She is performing oral sex, blowjob on a man whose erect penis is in her mouth. She is holding base of penis with her right hand. Man's nude lower torso and legs are partially visible.
```

#### All holes filled / Gangbang Cowgirl style (klein 9b)

- URL: https://civitai.red/models/2584578/all-holes-filled-gangbang-cowgirl-style-klein-9b
- Filename: ``FK_allholes.safetensors``

Trigger Words:
```text
the image shows one slender skinny girl and three men. all three men are penetrating the girl in some way. oral, anal and vaginal sex. the girl is turned with her ass to the camera in an half-side view on her body. her face is partially  visible from side.  the first man is lying on his back and the girl is straddling on him. he is covered by the girls upper body. the first man is penetrating the girls vagina, his testicles are visible and his penis visible penetrates her vagina. the face of the first man is not visible. the second man is standing behind the girl, his upper body and face is out of frame and not visible. the penis of the second man is clearly penetrating the girls anus, while the first man is penetrating her vagina. the third man is standing next to the girl. the man holds the penis of the third man in her mouth, performing oral sex on him. a photograph of a sexual scene. a woman is on all fours. she is performing oral sex on a man with a dark-skinned erect penis on the right. another man with a dark-skinned erect penis is behind her, penetrating her anus from behind. the men's bodies are partially visible, with one man's hand on her right buttock.
```

#### SexGod CowGirl Sex Style Klein 9b

- URL: https://civitai.red/models/2628000/sexgod-cowgirl-sex-style-klein-9b
- Filename: ``SEXGOD_Cowgirl_Klein9b_v1.safetensors``

Trigger Words:
```text
rev_c0wgirl
c0wgirl
```

#### Side anal / Spooning / Anal sex on side (Klein 9b)

- URL: https://civitai.red/models/2617836/side-anal-spooning-anal-sex-on-side-klein-9b
- Filename: ``FK_analonside.safetensors``
- Strength:
	- For legs closed: 0.8
	- For one leg up: 0.9

Trigger Words:
```text
image shows one girl and one man. the girl is lying on her side with her legs closed. she is exposing her vagina and anus. the man penetrates her anus with his large penis. focus is on the penetration of her anus and her thighs and ass., a photograph of a sexual scene. a woman lies on a white bed, a nude man with an erect penis is positioned to the left, his penis entering her anus. the woman's right hand is on her right thigh, and her left hand is on the bed. the man has a giant penis. he is black. the man s upper body is out of frame and his face not visible.

image shows one girl and one man. the girl is lying on her side with her legs closed. she is exposing her vagina and anus. the man penetrates her anus with his large penis. focus is on the penetration of her anus and her thighs and ass., A photograph of a sexual scene. A woman is lying on a white bed with her legs spread and bent at the knees. She has small breasts and is looking directly at the camera with a slightly open mouth. A nude Black man with dark skin and a muscular build is standing in front of her, penetrating her anus with his erect, uncircumcised penis.  the man s upper body is out of frame and his face not visible.

image shows one girl and one man. the girl is lying on her side and has one leg lifted up. her vagina and anus is visible. she is exposing her vagina and anus. the man penetrates her anus with his large penis. focus is on the penetration of her anus and her thighs and ass., a photograph of a sexual scene. a woman lies on a white bed, a nude man with an erect penis is positioned to the left, his penis entering her anus. the woman's right hand is on her right thigh, and her left hand is on the bed. the man has a giant penis. he is black. the man s upper body is out of frame and his face not visible. close-up shot,
```

#### Spreading legs PUSSY

- URL: https://civitai.red/models/2374533/spreading-legs-pussy
- Filename: ``nude_woman_v1.safetensors``
- Strength: 0.8

Trigger Words:
```text
pussy
```

#### Dildo insertion (klein 9b)

- URL: https://civitai.red/models/2564447/dildo-insertion-klein-9b
- Filename: ``FK_dildoinsertion.safetensors``
- Strength: 0.6-0.8

Trigger Words:
```text
the image shows one girl spreading her legs. she is inserting a dildo into her pussy. her pussy is visible and her legs apart. a photograph of a woman. her legs are spread apart, and she is inserting a large dildo into her shaved vulva with her hand.

she is sitting on a bed / bench / chair..... she is moaning and looking at viewer.
```