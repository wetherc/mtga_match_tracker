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


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    INFO = '\033[96m'
    SUCCESS = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


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
        print(f"❌ {bcolors.FAIL} Scryfall returned HTTP {res.status_code} for Arena card ID {id}.{bcolors.ENDC}")
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
    print(f"ℹ️ {bcolors.INFO} Loading session logfile...{bcolors.ENDC}")
    deck_data, match_data, match_commanders = load_mtga_logs(base_path, appdata_path)
    print(f"✅ {bcolors.SUCCESS} Loaded deck and match data from session logfile{bcolors.ENDC}")

    print(f"ℹ️ {bcolors.INFO} Validating session match data...{bcolors.ENDC}")
    try:
        assert len(deck_data) == len(match_data)
        print(f"✅ {bcolors.SUCCESS} Match data validated{bcolors.ENDC}")
    except AssertionError as error:
        print(f"⚠️ {bcolors.WARNING} Warning{bcolors.ENDC} ⚠️")
        print(f"Deck logs and match logs are of differing lengths ({len(deck_data)} != {len(match_data)}")
        print("Please review the parsed output for accuracy")

    print(f"ℹ️ {bcolors.INFO} Parsing match details...{bcolors.ENDC}")
    parsed_matches = parse_match_data(deck_data, match_data, player_name)
    print(f"✅ {bcolors.SUCCESS} Parsed match details{bcolors.ENDC}")

    print(f"ℹ️ {bcolors.INFO} Downloading commander card information from Scryfall...{bcolors.ENDC}")
    parsed_matches[["player_commander", "opponent_commander"]] = parsed_matches.apply(
        lambda x: get_player_commanders(x, match_commanders),
        axis=1)
    print(f"✅ {bcolors.SUCCESS} Downloaded commander card information{bcolors.ENDC}")

    parsed_matches = parsed_matches.drop(["player_seat", "opponent_seat"], axis=1)

    _winrate = round(
        sum(parsed_matches["game_won"]) / parsed_matches.shape[0] * 100,
        0)
    print(f"✅ {bcolors.SUCCESS} Details for {len(parsed_matches)} matches successfully identified{bcolors.ENDC}")
    print(f"ℹ️ {bcolors.INFO} Your winrate for this session was {_winrate}%{bcolors.ENDC}")

    print(f"ℹ️ {bcolors.INFO} Saving match win/loss data...{bcolors.ENDC}")
    if os.path.exists("match_history/mtga_match_log.csv"):
        parsed_matches.to_csv(
            "match_history/mtga_match_log.csv",
            index=False,
            header=False,
            mode="a")
    else:
        os.makedirs("match_history", exist_ok=True)
        parsed_matches.to_csv(
            "match_history/mtga_match_log.csv",
            index=False,
            header=True,
            mode="w")

    print(f"✅ {bcolors.SUCCESS} Saved matches to match_history/mtga_match_log.csv{bcolors.ENDC}")
    
    source_path = f"{base_path}/{appdata_path}/Player.log"
    destination_path = f"{base_path}/{appdata_path}/Player_{time.time_ns()}.log"
    # Ensure the source file exists
    print(f"ℹ️ {bcolors.INFO} Backing up session logfile data...{bcolors.ENDC}")
    if os.path.exists(source_path):
        shutil.move(source_path, destination_path)
        print(f"✅ {bcolors.SUCCESS} Session logfile moved from {source_path} to {destination_path}{bcolors.ENDC}")
    else:
        print(f"❌ {bcolors.FAIL} Session logfile {source_path} not found.{bcolors.ENDC}")


if __name__ == '__main__':
    parse_and_save_logs()