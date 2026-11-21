# Scanner setup

The built-in syntactic check runs without optional packages. Optional checks add detection; installing Petasos alone does not supply their models. The [generated scanner reference](../reference/scanners.md) names each check, what it looks for, its extra and its initial enablement. The [settings reference](../reference/settings.md) describes enablement choices and restart requirements.

## In Hermes

Use Overview's Checks panel or `petasos doctor` to see what is running and what is missing. Follow the command the report provides. `petasos scanner add prompt_guard` adds the model-based injection check's packages; `petasos scanner add presidio` adds the personal-information check's packages. Both update the plugin's dependency list and ask Hermes to rebuild its environment. Restart Hermes afterwards.

PromptGuard requires acceptance of the terms for [Meta's PromptGuard model](https://huggingface.co/meta-llama/Llama-Prompt-Guard-2-86M) and a Hugging Face token for its download, or a cached copy. Presidio needs its language model. Package installation alone does not prove either model can run. Check doctor again and follow the reported model instructions.

A check configured to run when installed is left out when its backend reports that it is absent. A required check that is absent, or an installed check that fails to load, remains an erroring participant: the configured failure policy applies. Disabling a check leaves it out deliberately. Use Settings to change enablement; removing packages and changing enablement are separate actions.

Semgrep cannot run inside Hermes because the adapter does not own its engine lifecycle. The form and commands refuse to turn it on or add it. A hand-written request for it still produces an unavailable check. Follow doctor's repair command, `petasos config set scanners.semgrep.enabled off`.

## In a library application

Install the extra named by the [registry reference](../reference/scanners.md) in the application's Python environment. `compose` in `petasos.scanners.registry` builds scanners from a config tree; pass its scanner tuple to `Pipeline`. Construct a custom scanner directly and pass it to the pipeline if it is outside the registry.

Semgrep requires an explicit lifecycle owner and separately installed engine. See [Semgrep deployment](../deployment/semgrep.md). See [library use](library.md) for the application boundary.
