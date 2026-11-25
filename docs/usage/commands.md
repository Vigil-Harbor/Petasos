# Everyday commands

Run Petasos commands in your own terminal, outside the guarded conversation. Use `--home` or `--profile` when you need to select a particular Hermes profile. Check the home printed by doctor before changing anything.

## Find out what is running

Run `petasos doctor`. Add `--verbose` for paths, versions and each resolved setting's origin, or `--json` for a script. Read the verdict and its next steps. Doctor examines the install and can ask Hermes to validate the plugin; it does not check that every running agent has restarted.

## Change protection

Use `petasos config set role coding` to select a job, or `petasos config set level strict` to choose strictness. These are examples; consult [jobs and strictness](jobs-and-strictness.md) before choosing. The command uses Hermes's settings writer and tells you when a change applies. Use Settings for lists and groups.

Run `petasos config set enabled false` to pause protection and `petasos config set enabled true` to resume. Paused calls pass unchecked and are recorded. Hermes must still load the plugin for its switch to matter.

## Add a check or repair an install

`petasos scanner add presidio` adds the personal-information check's packages to the plugin's dependency list and asks Hermes to rebuild its environment. `petasos scanner remove presidio` removes that extra. Restart Hermes afterwards; a running process keeps its environment. See [scanner setup](scanners.md) for model prerequisites.

`petasos hermes install --dry-run` previews a development refresh. `petasos hermes install` refreshes the plugin files and this build's wheel and enables the plugin through Hermes.

## Convert a settings file or fix a pin

`petasos config migrate` previews conversion of a flat `petasos:` section. Read its notes before adding `--write`; conversion uses Hermes's writer and leaves the source section in place. A pin prevents profile settings writes.

`petasos hermes pin` and `petasos hermes unpin` preview changes. Read [guardrail integrity](guardrail-integrity.md) before preparing either change with `--write`.

The [generated command reference](../reference/commands.md) contains all arguments and help, including the `hermes petasos` commands registered inside Hermes. Ask for help without making a change:

```bash
petasos config set --help
```
