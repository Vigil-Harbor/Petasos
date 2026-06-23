# Petasos Hermes plugin bundle

`manifest.json` `version` is the **plugin-bundle** version, deliberately
**independent** of the `petasos` Python package version (`petasos.__version__`).
The bundle ships on its own cadence; do not sync it to the package version.
(`manifest.json` is strict JSON and cannot carry an inline comment; this note
records the choice. PET-141.)
