-- Synthetic database only: no member, save or server data.
CREATE SCHEMA IF NOT EXISTS dune;
CREATE TABLE IF NOT EXISTS dune.actors (id bigint PRIMARY KEY, class text, map text);
CREATE TABLE IF NOT EXISTS dune.player_state (player_pawn_id bigint, account_id bigint, player_controller_id bigint, character_name text, online_status text);
CREATE TABLE IF NOT EXISTS dune.player_faction (actor_id bigint, faction_id bigint);
CREATE TABLE IF NOT EXISTS dune.factions (id bigint PRIMARY KEY, name text);
TRUNCATE dune.actors, dune.player_state, dune.player_faction, dune.factions;
INSERT INTO dune.actors VALUES (101,'BP_TestCharacter_C','Survival_1');
INSERT INTO dune.player_state VALUES (101,201,301,'Fixture, 生命','Offline');
INSERT INTO dune.factions VALUES (1,'Test faction');
INSERT INTO dune.player_faction VALUES (301,1);
