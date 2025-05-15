#!/usr/bin/env python3

import click
import json
import datetime
import requests
import shutil
import os
import sys
import time
import pandas as pd


class PrettyPrinter():
    def __init__(self):
        self.INFO = '\033[96m'
        self.SUCCESS = '\033[92m'
        self.WARNING = '\033[93m'
        self.FAIL = '\033[91m'
        self.ENDC = '\033[0m'
    
    def print_info(self, message: str) -> None:
        print(f"ℹ️ {self.INFO} {message}{self.ENDC}")
    
    def print_success(self, message: str) -> None:
        print(f"✅ {self.SUCCESS} {message}{self.ENDC}")
    
    def print_warning(self, message: str) -> None:
        print(f"⚠️ {self.WARNING} {message}{self.ENDC}")
    
    def print_fail(self, message: str) -> None:
        print(f"❌ {self.FAIL} {message}{self.ENDC}")


_printer = PrettyPrinter()


def load_mtga_logs(base_path: str, appdata_path: str):
    deck_data = []
    match_data = []
    match_commanders = {}
    
    _set_deck_string = "[UnityCrossThreadLogger]==> EventSetDeckV2 "
    
    with open(f"{base_path}/{appdata_path}/Player.log", "r") as f:
        for line in f.readlines():
            if "GameStage_Start" in line:
                line = json.loads(line)
    
                commander_blob = [
                    message for message in line["greToClientEvent"]["greToClientMessages"]
                    if message["type"] == "GREMessageType_GameStateMessage"
                ][0]["gameStateMessage"]["gameObjects"]
    
                match_id = [
                    message for message in line["greToClientEvent"]["greToClientMessages"]
                    if message["type"] == "GREMessageType_GameStateMessage"
                ][0]["gameStateMessage"]["gameInfo"]["matchID"]
                
                if match_id not in match_commanders.keys():
                    match_commanders[match_id] = [{
                        "player_seat_id": player["ownerSeatId"],
                        "commander": player["grpId"]
                    } for player in commander_blob]
            elif line.startswith(_set_deck_string):
                # 🥲
                # but can also save off the full decklist if we want from this
                deck_data.append(
                    json.loads(
                        json.loads(
                            line[(len(_set_deck_string)):].replace("\n", "")
                        )["request"]
                    )
                )
            elif '"stateType": "MatchGameRoomStateType_MatchCompleted"' in line:
                match_data.append(json.loads(line))
        return deck_data, match_data, match_commanders


def parse_match_data(deck_data, match_data, player_name) -> pd.DataFrame:
    match_data_parsed = []
    
    for deck, match in zip(deck_data, match_data):
        player_seat = [
            player["teamId"] for player in match["matchGameRoomStateChangedEvent"]["gameRoomInfo"]["gameRoomConfig"]["reservedPlayers"]
            if player["playerName"] == player_name
        ][0]
        
        _match_data = {
            "game_id": match["matchGameRoomStateChangedEvent"]["gameRoomInfo"]["gameRoomConfig"]["matchId"],
            "timestamp": datetime.datetime.fromtimestamp(int(match["timestamp"]) / 1000),
            "deck_name": deck["Summary"]["Name"],
            "opponent": [
                player["playerName"] for player in match["matchGameRoomStateChangedEvent"]["gameRoomInfo"]["gameRoomConfig"]["reservedPlayers"]
                if player["playerName"] != player_name
            ][0],
            "game_won": [
                result.get("winningTeamId", None) for result in match["matchGameRoomStateChangedEvent"]["gameRoomInfo"]["finalMatchResult"]["resultList"]
                if result["scope"] == "MatchScope_Match"
            ][0] == player_seat,
            "game_result_reason": [
                result["reason"] for result in match["matchGameRoomStateChangedEvent"]["gameRoomInfo"]["finalMatchResult"]["resultList"]
                if result["scope"] == "MatchScope_Match"
            ][0],
            "player_seat": player_seat,
            "opponent_seat": 3 - player_seat,
        }
    
        match_data_parsed.append(_match_data)
    return pd.DataFrame(match_data_parsed)


def get_scryfall_name_from_arena_id(id: int):
    res = requests.get(f"https://api.scryfall.com/cards/arena/{id}")
    if res.status_code != 200:
        _printer.print_fail(f"Scryfall returned HTTP {res.status_code} for Arena card ID {id}")
        return id
    card_data = json.loads(res.text)
    return card_data.get("name", id)


def get_player_commanders(match_data_row: pd.Series, match_commanders) -> pd.Series:
    _match = match_data_row["game_id"]
    try:
        result = pd.Series([
            get_scryfall_name_from_arena_id([
                player["commander"] for player in match_commanders[_match]
                if player["player_seat_id"] == match_data_row["player_seat"]
            ][0]),
            get_scryfall_name_from_arena_id([
                player["commander"] for player in match_commanders[_match]
                if player["player_seat_id"] == match_data_row["opponent_seat"]
            ][0])
        ])
    except KeyError:
        # In cases of a player disconnect or backend issue when matching,
        # the match can immediately result in a draw with no player commander
        # data ever being returned to the client
        result = pd.Series([None, None])

    return result


@click.command()
@click.option(
    "--base-path",
    default="/mnt/c/Users/chris",
    help="Absolute path of target user's home directory")
@click.option(
    "--appdata-path",
    default="AppData/LocalLow/Wizards Of The Coast/MTGA",
    help="Relative path from user's home directory of MTGA game files")
@click.option(
    "--player-name",
    default="spantz",
    help="User's MTGA display name")
def parse_and_save_logs(base_path: str, appdata_path: str, player_name: str):
    _printer.print_info("Loading session logfile...")
    try:
        deck_data, match_data, match_commanders = load_mtga_logs(base_path, appdata_path)
    except FileNotFoundError:
        _printer.print_fail(f"Unable to locate MTGA Player.log. Script exiting")
        sys.exit(1)
    _printer.print_success("Loaded deck and match data from session logfile")

    _printer.print_info("Validating session match data...")
    try:
        assert len(deck_data) == len(match_data)
        _printer.print_success("Match data validated")
    except AssertionError as error:
        _printer.print_warning("Warning")
        _printer.print_warning(f"Deck logs and match logs are of differing lengths ({len(deck_data)} != {len(match_data)}")
        _printer.print_warning("Please review the parsed output for accuracy")

    _printer.print_info("Parsing match details...")
    parsed_matches = parse_match_data(deck_data, match_data, player_name)
    _printer.print_success("Parsed match details")

    _printer.print_info("Downloading commander card information from Scryfall...")
    parsed_matches[["player_commander", "opponent_commander"]] = parsed_matches.apply(
        lambda x: get_player_commanders(x, match_commanders),
        axis=1)
    _printer.print_success("Downloaded commander card information")

    parsed_matches = parsed_matches.drop(["player_seat", "opponent_seat"], axis=1)

    _winrate = round(
        sum(parsed_matches["game_won"]) / parsed_matches.shape[0] * 100,
        0)
    _printer.print_success(f"Details for {len(parsed_matches)} matches successfully identified")
    _printer.print_info(f"Your winrate for this session was {_winrate}%")

    _printer.print_info("Saving match win/loss data...")

    script_path = os.path.abspath(os.path.dirname(sys.argv[0]))
    if os.path.exists(f"{script_path}/match_history/mtga_match_log.csv"):
        parsed_matches.to_csv(
            f"{script_path}/match_history/mtga_match_log.csv",
            index=False,
            header=False,
            mode="a")
    else:
        os.makedirs(f"{script_path}/match_history", exist_ok=True)
        parsed_matches.to_csv(
            f"{script_path}/match_history/mtga_match_log.csv",
            index=False,
            header=True,
            mode="w")

    _printer.print_success("Saved matches to ./match_history/mtga_match_log.csv")
    
    source_path = f"{base_path}/{appdata_path}/Player.log"
    destination_path = f"{base_path}/{appdata_path}/Player_{time.time_ns()}.log"
    # Ensure the source file exists
    _printer.print_info("Backing up session logfile data...")
    if os.path.exists(source_path):
        shutil.move(source_path, destination_path)
        _printer.print_success(f"Session logfile moved from {source_path} to {destination_path}")
    else:
        _printer.print_fail(f"Session logfile {source_path} not found.")


if __name__ == '__main__':
    parse_and_save_logs()