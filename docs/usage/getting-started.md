# Getting started with Hermes

Petasos checks an agent's tool calls and the text tools return. Install it in each Hermes profile you want guarded. The supported host requirement is declared in the [plugin manifest](../../hermes-plugin/petasos/plugin.yaml).

## Install and check

For a published release, use the one-command install in the [README](../../README.md). For a development checkout installed in your Python environment, run `petasos hermes install`. This packages that build as a wheel in the plugin directory and asks Hermes to install it into the environment new Hermes processes use. Running the command again refreshes the plugin files and wheel.

Use `petasos hermes install --dry-run` to preview the development install. Add `--home /tmp/petasos-docs-home` when you want a throwaway target rather than the home Hermes selects. `--profile` selects a named profile under the target home; see the [command reference](../reference/commands.md).

Restart Hermes after installation so it uses the new environment. Open the Petasos tab in Hermes's dashboard and run `petasos doctor`. Read the report's next steps if a check is missing, settings are rejected, or Hermes is not loading Petasos. The report checks the install; it does not prove that every running agent has adopted a change.

## Make the two choices

Choose a job and strictness in Overview or Settings. [Jobs and strictness](jobs-and-strictness.md) explains how the choices combine. Settings shows individual changes and says which need a restart. Hermes Desktop also exposes the basic plugin settings.

Overview shows which checks are running or missing. [Scanner setup](scanners.md) explains how to add one. Activity shows recorded enforcement events. Try it checks a sample using a private trial: it runs no tool, changes no conversation and adds no Activity record. Its risk score describes that input alone.

## Check who can change protection

Hermes's plugin list controls whether Petasos loads. Petasos's Protection switch pauses its checks while the plugin stays loaded. Doctor and Overview show both switches.

Read [guardrail integrity](guardrail-integrity.md) before allowing unattended work or handing the agent powerful tools. A recognized attempt to change a guardrail needs a person or is refused; account permissions still determine what a disguised write can change.

The [host evidence](../architecture/hermes-host-facts.md) records isolated checks. A live gateway and a kanban worker were not exercised there; settings refresh in those processes still needs operator verification.
