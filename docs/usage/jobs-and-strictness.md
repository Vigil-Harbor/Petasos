# Jobs and strictness

A job (`role`) says what the agent does. Strictness (`level`) says how soon a conversation's warning signs add up to blocked tool calls. They change different settings, so choosing one does not undo the other.

Pick the job whose description fits the work, then read the strictness descriptions and choose the interruption level you can accept. The [generated job and strictness tables](../reference/layers.md) contain every choice, its description and exactly what it sets. A suggested strictness is advice; choosing a job does not apply the suggestion.

## Shell commands

General and coding ask before risky commands. When Hermes will ask about the
same terminal command, Petasos records the finding and leaves that prompt to
Hermes. If Tirith is loaded too, Petasos leaves pipes to a shell, decoded
execution and fetched scripts to Tirith. Activity names who checks the
command. Try it shows Petasos's decision; it does not run Tirith.

A blocking job still blocks. So do yolo and unattended settings that would
approve every ask. Petasos keeps its other checks, including destructive
commands, personal data leaving the agent and attempts to change protection.
For a command with several findings, each must have another checker before
Petasos steps aside. Use Settings to choose a job. Run
`hermes petasos doctor` to see the explanation when both plugins are loaded.

## Your changes

Petasos resolves the schema's settings, then the job, then strictness, then `overrides`. An override wins over the earlier layers. A list in a layer or override replaces the list beneath it; it does not add to that list. Mappings merge by key.

Settings shows where each value came from and lets you reset an override. After changing the job, review any overrides: they still win. Use Try it to check a representative input before saving. Fields that need a restart are identified in the [settings reference](../reference/settings.md) and in the save result.

## Hermes profiles

A profile is a Hermes home with its own plugin settings and enforcement state. The tab follows the home Hermes selects for the request. Install Petasos for every profile that needs it, and use the command's `--home` and `--profile` options to target the intended one. A [machine-level pin](guardrail-integrity.md) fixes values across every profile using that managed directory.
