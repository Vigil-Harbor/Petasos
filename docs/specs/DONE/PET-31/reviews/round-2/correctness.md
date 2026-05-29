# Correctness Review — Round 2

All R1 findings CLOSED. New findings:

### F-1 (P0): config.copy() in Pipeline.__init__ strips session_secret — entire feature dead on arrival
Pipeline.__init__ calls config.copy() which chains to_dict()→from_dict(). D11 excludes session_secret from to_dict(). So self._config.session_secret is always None inside Pipeline. Token minting never activates. FrequencyTracker also gets None.

### F-2 (P2): Guard's tracker and Pipeline's tracker are different objects
ToolCallGuard is constructed with a separate FrequencyTracker. Both must receive configs with session_secret.

### F-3 (P2): copy() secret loss may break non-Pipeline callers
Only current in-repo copy() call is Pipeline.__init__.

STATUS: RED P0=1 P1=0 P2=2 P3=0 P4=0
