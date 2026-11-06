"""Explicit strength boundary fixtures for tests of unrelated native fields.

Full legal-roster scoring is exercised by test_tournament_sim_strength and
test_tournament_sim_lifecycle. These old protocol tests intentionally use
one-player or synthetic parameter rows, so they must inject their inputs.
"""
import copy
from unittest.mock import patch


def snapshot(team,generator,conn,*,squad=None,player_pool=None):
    result=copy.deepcopy(team)
    if squad is not None:result['squad_data']=copy.deepcopy(squad)
    if player_pool is not None:
        values=player_pool.values()if isinstance(player_pool,dict)else player_pool
        pool={(p['gameplayer_id']['id'],p['gameplayer_id']['serial']):p for p in values}
        result['player_list']=[copy.deepcopy(pool[(r['gameplayer_id']['id'],r['gameplayer_id']['serial'])])
                               for r in result['squad_data']['player_list']]
    return result


def patch_strength(test):
    for target,value in(('tournament_runtime._strength_snapshot',snapshot),
                         ('tournament_runtime._team_ratings',lambda *a,**k:
                          dict(attack=80,creation=80,defence=80,goalkeeping=80,depth=80,
                               audit={'source':'explicit unrelated-protocol test fixture'}))):
        handle=patch(target,side_effect=value);handle.start();test.addCleanup(handle.stop)
