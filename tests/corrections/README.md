# Fixes from Matcher, as test cases

Each CSV here lists descriptions people matched in [Matcher](../../matcher/) and the block or intersection they picked by hand when the matcher got it wrong. They come from Matcher's **Share with sf-blocks** button (which opens GitHub with the file filled in) or **Save fixes**.

`scripts/test_matcher.py` runs every description through `match_blocks.py` and compares:

```
python3 scripts/test_matcher.py              # how many it gets right; exits 1 if one it used to get right is now wrong
python3 scripts/test_matcher.py --failing    # also list the ones it still gets wrong: the to-do list for the matcher
python3 scripts/test_matcher.py --update     # after improving the matcher, record which pass now
```

`baseline.json` records which cases passed last time. The pull-request check runs the script, so a change to the matcher that breaks a fix it used to get right fails the check. A new file of fixes doesn't fail it: its cases aren't in the baseline until someone improves the matcher and runs `--update`.

| Column | What it is |
|---|---|
| `text` | What the matcher read: the description, or "Street & Cross" built from separate columns |
| `part` | Which location in that description (a row naming two blocks has parts 1 and 2) |
| `expected_type`, `expected_cnn` | What the person picked: `block` or `intersection`, and the CNNs (";"-separated). Empty means "no match" |
| `matcher_cnn`, `matcher_confidence` | What the matcher said before the fix |
| `source`, `fixed_on` | The file it came from and the date |
| `note` | Anything worth knowing, written by hand |

These files are public. Matcher only puts the location text and CNNs in them, never a row's other columns. Check before merging that a description doesn't include a name or other personal detail.
