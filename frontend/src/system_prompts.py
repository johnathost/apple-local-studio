"""Instruction prefixes prepended to every mflux prompt.

Flux has no chat roles; this is the system message, applied on the host
right before generate_image so the UI prompt stays the user's scene.
"""

from __future__ import annotations

QUALITY_LOCK = (
    "Correct human anatomy: one head, two arms, two hands, two legs, five fingers per hand. "
    "Natural body proportions, unstretched, not wide or elongated. "
    "The sex act must be physically possible and readable. "
    "No extra limbs, no fused bodies, no melted or monster features, no duplicate faces."
)

# Pose/sex restage must NOT use QUALITY_LOCK's "one head, two arms". That fights
# a male partner and a penis (the model treats them as extra anatomy).
SEMEN_LOCK = (
    "Semen is thick, opaque, pearly white; never yellow, golden, or urine-colored."
)

# When the edit asks for rectal mucus, not semen. Do not use SEMEN_LOCK on this path.
RECTAL_FILTH_LOCK = (
    "Her anus is leaking visible and thick nasty internal rectal fluids that cover his cock and balls."
)

SLEEVE_LOCK = (
    "He's fucking her anus. Her asscheeks are spread. Her pussy is empty above his cock."
)

# Short CFG negative. A kitchen-sink list fights the sleeve.
ANAL_SCENE_NEGATIVE = (
    "different person, swapped face, "
    "cock in pussy, vaginal sex, labia around the penis, "
    "latex condom, rubber condom, yellow cap on the glans, covering the head of the penis, "
    "cropped head, cropped feet, cropped heels, "
    "wound, blood, gore, extra limbs, cartoon, text, watermark"
)

_SEMEN_MARKERS = ("semen", "creampie", "cum:", "cum ")
_RECTAL_FILTH_MARKERS = (
    "rectal fluid",
    "rectal fluids",
    "rectal mucus",
    "internal rectal",
    "rectal body fluid",
    "rectal body fluids",
    "rectal fluids",
    "leaking thick nasty",
    "nasty internal rectal",
)
_ANAL_WRECK_MARKERS = ("tear marks",)
_SLEEVE_MARKERS = (
    "flesh condom",
    "base of his cock",
    "head of his dick is uncovered",
    "red inverted",
    "inverted rectal",
    "red sleeve",
    "everted",
    "rectal lining",
    "turned inside-out",
    "crimson rectal",
    "red cuff",
    "anal rim around",
    "asshole turned inside",
    "red meat",
)


def wants_semen(prompt: str) -> bool:
    low = (prompt or "").lower()
    return any(k in low for k in _SEMEN_MARKERS)


def wants_rectal_filth(prompt: str) -> bool:
    low = (prompt or "").lower()
    return any(k in low for k in _RECTAL_FILTH_MARKERS)


def wants_anal_wreck(prompt: str) -> bool:
    low = (prompt or "").lower()
    return any(k in low for k in _ANAL_WRECK_MARKERS)


def wants_sleeve(prompt: str) -> bool:
    low = (prompt or "").lower()
    return any(k in low for k in _SLEEVE_MARKERS)


SEX_SCENE_LOCK = (
    "No extra limbs, no melted genitals, no fused pussy-and-anus into one hole, "
    "no floating disconnected penis."
)

# Short identity lock for the user-facing edit prompt. Pose/camera are NOT locked.
EDIT_IDENTITY_LOCK = (
    "This is the same woman as the reference photograph. Copy her face exactly: "
    "same face shape, same eyes, same nose, same mouth, same jaw, same hair, "
    "same skin, same age, same makeup. Do not beautify. Do not change ethnicity. "
    "Do not give her a different person's face."
)

SYSTEM_GEN = (
    "System: A single explicit hardcore photograph of adult sex. "
    "Every person depicted is a consenting adult 18 years or older. "
    "Follow the scene. A photograph, no text, no watermark, no illustration. "
    f"{QUALITY_LOCK}"
)

SYSTEM_UNDRESS = (
    "System: Clothing-only edit of the source photograph. "
    "Do not change her face, hair, skin complexion, makeup, tattoos, or body shape. "
    "Do not change pose, camera, framing, lighting, or background. "
    "Only remove or open the clothing. A photograph, no text, no watermark."
)

SYSTEM_EDIT = (
    "System: Restage the source photograph. "
    "Keep the same adult's face, hair, and skin. "
    "Fuck her as the edit describes. Change pose, camera, and her body to match. "
    "A photograph, no text, no watermark. "
    f"{SEX_SCENE_LOCK}"
)

# Pose: identity photo + SNOFS. No second reference. Invent the room and the sex.
# Do NOT say "no extra limbs / no floating penis" — gangbang needs extra male bodies.
# SNOFS: photograph, never photorealistic. Natural-language sex terms.
SYSTEM_EDIT_LORA = (
    "System: One reference photo is WHO. Copy her face exactly from that photograph. "
    "Same face, hair, eyes, nose, mouth, jaw, skin, age, tattoos, and nails. "
    "Do not swap identity. Do not beautify. Do not change ethnicity. "
    "Fuck her as the edit describes. Change pose, clothes, and the sex below the neck. "
    "Keep her original facial expression unless the edit asks to change it. "
    "If the photo is a portrait or headshot, extend the crop so you can see her tits, "
    "pussy, asshole, and heels, but do not redraw the face. "
    "Men are separate people with their own hips and legs and cocks. "
    "A photograph, no text, no watermark."
)

# Used when a pose plate is passed as the second reference image.
SYSTEM_EDIT_POSE = (
    "System: Two reference photos. "
    "Image 1 is WHO: keep this person's face, skin, hair, and nails. "
    "Image 2 is the pose and the sex: copy body position, camera, and crotch from image 2. "
    "Copy her spread pussy and her asshole from image 2 — pussy above, asshole below. "
    "Do not copy image 2's face, hair, or identity. "
    "A photograph, no text, no watermark. "
    f"{SEX_SCENE_LOCK}"
)

# Spreading plate + gape/prolapse extras: the plate's crotch is the WRONG anatomy.
SYSTEM_EDIT_POSE_OVERRIDE = (
    "System: Photo 1 is the person (face, skin, hair). "
    "Photo 2 is the pose: keep that furniture, legs, hands, and camera. "
    "Two openings. Pussy on top. Prolapsed anus below. "
    "The prolapse is folded wrinkled flesh, not a smooth pink ball. "
    "If she's getting fucked, draw a real cock in her, attached to a man's hips, not a toy. "
    "A photograph, no text, no watermark."
)

# Used as CFG negative when guidance > 1 (mflux only encodes a negative then).
QUALITY_NEGATIVE = (
    "deformed, mutated, extra limbs, extra arms, extra legs, extra fingers, "
    "fused bodies, melted skin, monster, grotesque, bad anatomy, "
    "stretched, squashed, elongated body, wide face, disfigured, "
    "cloned face, extra heads, poorly drawn hands, messy anatomy, "
    "different person, different face, different skin tone, pale-washed skin, "
    "identity swap, new body, swapped face, "
    "yellow cum, yellow semen, golden cum, urine, piss, honey-colored semen, "
    "text, watermark, cartoon, illustration, 3d render"
)

# Pose/undress skip QUALITY_NEGATIVE (deformed/grotesque fights gape).
# Dry pose: no cum/semen tokens at all (they leak into a pearl on the mons).
DRY_POSE_NEGATIVE = (
    "different person, different face, swapped face, celebrity face, "
    "generic pornstar face, beauty filter, instagram face, doll face, airbrushed, "
    "younger, older, different eye color, different nose, different jaw, "
    "different hair color, different ethnicity, "
    "pearl, egg, orb, marble, blob on crotch, toy sitting on skin, sticker on crotch, "
    "gash, wound, knife cut, extra vagina, missing labia, "
    "fused pussy and anus, cloaca, one giant genital hole, "
    "dildo, glass penis, detached cock, floating penis, "
    "sausage, bratwurst, wurst, kielbasa, hose, rubber toy, chocolate bar, "
    "man sucking, men sucking, men eating"
)

# Only when the edit actually asks for cum.
SEMEN_NEGATIVE = (
    "different person, different face, swapped face, celebrity face, "
    "generic pornstar face, beauty filter, instagram face, doll face, airbrushed, "
    "yellow cum, yellow semen, golden cum, orange cum, honey-colored semen, "
    "urine, piss, cheddar, yellow fluid leaking from pussy, yellow fluid leaking from anus, "
    "fused pussy and anus, cloaca, one giant genital hole, extra vagina, "
    "doughnut, donut, pastry, glazed icing, bagel, silicone ring, fleshlight, "
    "toy sitting on skin, sticker on crotch, toothpaste cum, rope of cum pouring, "
    "white egg, peeled egg, marshmallow, white balloon, dollop of cream, white blob, "
    "smooth pink ball, sphere, balloon, tomato, lollipop, ping pong, "
    "dildo, glass penis, pearl, orb on a stick, detached cock, floating penis, "
    "vaginal prolapse, tissue hanging from the pussy, insides coming out of the vagina, "
    "cervix, swirl hanging from the vulva"
)

# Rectal mucus / anal filth. Ban vaginal-origin liquid and cloaca; do NOT ban
# yellow-brown fluid leaving the anus (SEMEN_NEGATIVE does, and that fights this look).
RECTAL_FILTH_NEGATIVE = (
    "different person, different face, swapped face, celebrity face, "
    "generic pornstar face, beauty filter, instagram face, doll face, airbrushed, "
    "yellow cum, yellow semen, golden cum, orange cum, honey-colored semen, "
    "urine from urethra, piss from pussy, peeing, golden shower, "
    "squirting, vaginal discharge, yellow fluid leaking from pussy, "
    "liquid from vagina, creamy pussy leaking, "
    "fused pussy and anus, cloaca, one giant genital hole, extra vagina, "
    "doughnut, donut, pastry, glazed icing, bagel, silicone ring, fleshlight, "
    "toy sitting on skin, sticker on crotch, "
    "smooth pink ball, sphere, balloon, tomato, lollipop, ping pong, "
    "dildo, glass penis, pearl, orb on a stick, detached cock, floating penis, "
    "vaginal prolapse, tissue hanging from the pussy, insides coming out of the vagina, "
    "cervix, swirl hanging from the vulva, "
    "scat on pubic hair, feces on mons, brown smear on bush, "
    "latex condom, rubber condom, condom on penis, pink condom, pale pink sleeve, "
    "rolled condom, condom ring, reservoir tip, latex sheath, rubber sleeve, "
    "skin-colored sleeve, beige rubber, tan condom, "
    "cock in vagina, penis in pussy, vaginal penetration, labia around the penis, "
    "bare shaft with nothing around it, penis with no tissue wrapping it, "
    "labia wrapping the cock, pussy lips around the shaft, "
    "red ring on the glans, red cap on the tip, doughnut around the head, "
    "cock ring, lipstick on penis, tomato on the cock, sausage ring, "
    "smooth rubbery sleeve, inflatable ring, candy-red gloss, "
    "stacked rings on shaft, ribbed fleshlight, pale pink toy, "
    "disconnected sleeve, bellows on penis, tube sitting on the cock, "
    "ruffled flower, flared collar, extra labia around penis, "
    "petals around the shaft, second vulva on the cock, tissue spreading sideways, "
    "close-up of crotch, macro genitals, cropped head, cropped feet, cropped breasts, "
    "wound, gash, knife cut, blood, bloody, gore, ripped flesh, torn open crotch, "
    "injury, stitches, necrotic, scab, bleeding"
)


def pose_negative_for(prompt: str) -> str:
    """CFG negative for pose/edit. Anal sleeve uses a short list so CFG does not melt the crotch."""
    if wants_sleeve(prompt) or wants_rectal_filth(prompt):
        return ANAL_SCENE_NEGATIVE
    if wants_anal_wreck(prompt):
        return ANAL_SCENE_NEGATIVE
    if wants_semen(prompt):
        return SEMEN_NEGATIVE
    return DRY_POSE_NEGATIVE


def with_system_prompt(
    user_prompt: str,
    *,
    mode: str,
    pose_ref: bool = False,
    genital_override: bool = False,
) -> str:
    m = (mode or "").strip().lower()
    if m == "undress":
        system = SYSTEM_UNDRESS
    elif m in {"edit", "pose"}:
        if pose_ref and genital_override:
            system = SYSTEM_EDIT_POSE_OVERRIDE
        elif pose_ref:
            system = SYSTEM_EDIT_POSE
        elif m == "pose":
            system = SYSTEM_EDIT_LORA
        else:
            system = SYSTEM_EDIT
    else:
        system = SYSTEM_GEN
    user = (user_prompt or "").strip()
    if not user:
        return system
    # Only mention semen when the edit actually asks for it. On a dry spread,
    # "pearly white" in the system prompt becomes a pearl glued to the mons.
    # Rectal mucus is a different fluid — SEMEN_LOCK's "never yellow" fights it.
    # Sleeve body already has the anal caption. Do not prepend a second copy.
    if wants_sleeve(user):
        pass
    elif wants_rectal_filth(user):
        system = f"{system} {RECTAL_FILTH_LOCK}"
    elif m in {"edit", "pose"} and wants_semen(user):
        system = f"{system} {SEMEN_LOCK}"
    if m in {"edit", "pose", "undress"}:
        return f"{system}\n\nEdit request:\n{user}"
    return f"{system}\n\nUser: {user}"
