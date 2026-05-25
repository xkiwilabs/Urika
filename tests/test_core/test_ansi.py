def test_strip_ansi_covers_decsc_decrc_and_osc():
    from urika.core.ansi import strip_ansi

    assert strip_ansi("a\x1b7b\x1b8c") == "abc"  # Fp DECSC/DECRC
    assert strip_ansi("x\x1b]0;title\x07y") == "xy"  # OSC + BEL
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"  # CSI
    assert strip_ansi("plain") == "plain"
    assert strip_ansi("") == ""


def test_strip_ansi_matches_run_log_behavior():
    # The shared helper must be at least as aggressive as the old run_log regex.
    from urika.core.ansi import strip_ansi

    sample = "\x1b[1;36m[planning]\x1b[0m starting\x1b7 saved\x1b8 restored"
    out = strip_ansi(sample)
    assert "\x1b" not in out
