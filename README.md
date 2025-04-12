# MTGA Brawl Tracker

This provides a Jupyter notebook for parsing win/loss information from [MTGA debug logs](https://mtgarena-support.wizards.com/hc/en-us/articles/360000726823-Creating-Log-Files-on-PC-Mac-Steam).

Notably, I have only tested this on Historic Brawl matches. Although it generally works well, it's still a bit jank and doesn't handle every use case that you're likely to encounter (e.g., if you leave the queue before matching with an opponent, the script might have a bad day).


## Usage

The only parameters that you need to modify are `BASE_PATH`, `APP_DATA_PATH`, and `PLAYER_NAME` at the start of the notebook. These should correspond to:

  - `BASE_PATH` --- the absolute path on disk to, generally, your user profile. E.g., `C:\Users\<username>` / `/home/<username>` / etc. This may vary depending on your operating system and any quirks of your specific setup;
  - `APP_DATA_PATH` --- the relative path from your user profile where MTGA logs are stored. On Windows, this will generally be at `AppData\LocalLow\Wizards Of The Coast\MTGA`
  - `PLAYER_NAME` --- your MTGA display name. This is case sensitive.

Running the notebook top to bottom will create a new CSV, or append if one already exists, that includes:

  - `game_id`: the match GUID;
  - `timestamp`: the start time of the match;
  - `deck_name`: the name of the deck you played;
  - `opponent`: your opponent's MTGA display name;
  - `game_won`: a boolean indicator of whether you won (`True`) or lost (`False`) the match;
  - `game_result_reason`: how the game outcome was determined (usually either by a life total going to 0, `ResultReason_Game`, or by concession, `ResultReason_Concede`);
  - `player_commander`: the name of your deck's commander card;
  - `opponent_commander`: the name of your opponent's commander card

Note that in cases where Scryfall does not recognize an Arena card ID (usually if you're matching against commanders from a newly released set), the MTGA card ID will be left in place of the commander name. This can be retroactively updated after the Scryfall database updates to include the card's MTGA ID.


## FAQ

### Why'd you make this?

I was bored and like hoarding data.

### Is this stable?

No.

### Can I use this for other formats?

Possibly! I haven't tested it with anything besides Historic Brawl
