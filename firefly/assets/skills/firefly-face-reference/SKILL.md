---
name: firefly-face-reference
description: Use this skill whenever the user asks Codex to generate, edit, refine, or describe Firefly / 流萤 images, especially when the user mentions 流萤, Firefly, 崩坏星穹铁道, Honkai: Star Rail, or asks to keep her face, eyes, hair, or character features consistent. The skill provides a saved face-and-eye reference image and a workflow for making Firefly's face and eyes match the user's preferred reference across outfit, pose, and scene changes.
---

# Firefly Face Reference

## Core Rule

Always treat `assets/firefly-face-reference.png` as the primary face and eye reference for Firefly / 流萤 image work.

If the user provides another image for pose, clothing, scene, or style, assign image roles explicitly:

- Saved reference: face, eyes, hair, headband, and character identity.
- User-provided reference: pose, outfit, camera angle, scene, lighting, or style, unless the user says otherwise.

Read `references/face-eye-reference.md` before writing prompts for Firefly image generation or edits.

## Workflow

1. Load or inspect `assets/firefly-face-reference.png` when generating or editing Firefly images.
2. Extract the current task goal: new image, edit, pose change, clothing change, camera change, or style change.
3. Write the prompt so the saved reference controls Firefly's face and eyes at highest priority.
4. Preserve the user's requested outfit, pose, scene, or edit while keeping these identity anchors:
   silver-white hair, center bangs, black headband, teal hair accent, pale green leaf-like side ornament, soft oval face, tiny gentle smile, and blue-pink gradient eyes.
5. For image generation, pass the saved reference image as an input reference whenever the image tool supports references.
6. If another reference image is used, mention both roles in the prompt so the generator does not use the outfit/pose image as the face reference.
7. After generation, check the face and eyes against the saved reference. If the eyes become plain blue, green, black, or purple-only, regenerate with a stricter eye prompt.

## Prompt Requirements

Include a compact version of this identity prompt in every Firefly image request:

```text
Use the saved Firefly face reference for identity: soft oval youthful-adult face, small gentle smile, silver-white hair with center bangs, black headband with teal accent, pale green leaf-like side hair ornament, and large glossy blue-pink gradient eyes with cyan/blue-violet outer iris, vivid rose-pink/magenta oval center pupil, pink-lavender lower iris, and glass-like white/cyan highlights.
```

When the user asks for a clothing or pose change, add:

```text
Change only the requested outfit/pose/scene. Keep Firefly's face, eyes, hair, headband, and side hair ornament consistent with the saved reference.
```

## Quality Checks

Before finishing, verify:

- The eyes are not plain blue, green, black, brown, or single-color purple.
- The center pupil has a rose-pink or magenta oval look.
- The lower iris has pink-lavender or pink-purple tones.
- The face stays softly oval with a small calm smile.
- The silver-white hair, center bangs, black headband, teal accent, and pale green side ornament remain visible.
- No text, watermark, logo, extra character, or unwanted face-style drift appears.

If any core face or eye feature is missing, make one targeted regeneration or edit pass focused only on identity correction.
