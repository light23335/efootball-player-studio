"""V17 native integer overall, independently checked against ARM64 0x82b5bb0.

The weights at 0xcd7170 and the native 147-field mapping are verified against
original engine efd257d9e41b622d6ecb8f51f7b0a8ee8820113fd427c5572025df1c8eecc7b8.
No regression coefficients or saved _overall metadata are read.
"""
PARAMETERS = (47, 14, 18, 17, 19, 21, 22, 20, 27, 28, 23, 15, 24, 25, 37, 34, 38, 35, 36, 39, 16, 32, 29, 30, 31, 40, 33, 26)
WEIGHTS = ((186, 136, 49, 49, 61, 37, 12, 12, 37, 49, 49, 62, 99), (0, 14, 61, 61, 61, 98, 98, 98, 171, 159, 159, 173, 210), (13, 27, 86, 86, 122, 171, 171, 171, 196, 159, 159, 210, 123), (0, 14, 61, 61, 37, 98, 110, 122, 122, 159, 159, 123, 62), (0, 0, 37, 37, 24, 49, 73, 61, 73, 86, 86, 86, 37), (27, 41, 61, 61, 122, 208, 135, 135, 196, 73, 73, 99, 37), (40, 68, 147, 147, 122, 159, 196, 196, 159, 98, 98, 74, 12), (0, 27, 24, 24, 37, 73, 86, 86, 184, 159, 159, 284, 358), (0, 14, 24, 24, 12, 12, 24, 24, 12, 12, 12, 12, 12), (0, 14, 24, 24, 12, 12, 24, 24, 12, 12, 12, 12, 12), (0, 55, 24, 24, 61, 24, 12, 12, 24, 24, 24, 25, 62), (13, 286, 147, 147, 220, 86, 49, 49, 24, 12, 12, 0, 0), (0, 191, 86, 86, 122, 86, 24, 24, 24, 12, 12, 12, 12), (0, 82, 37, 37, 98, 37, 12, 12, 12, 12, 12, 12, 12), (53, 27, 24, 24, 49, 73, 24, 24, 73, 61, 61, 99, 123), (13, 136, 220, 220, 61, 61, 196, 196, 98, 220, 220, 86, 99), (40, 150, 184, 184, 61, 86, 159, 159, 86, 159, 159, 99, 123), (80, 204, 98, 98, 122, 49, 24, 24, 24, 37, 37, 37, 86), (0, 0, 24, 24, 12, 24, 61, 61, 24, 73, 73, 74, 86), (133, 109, 37, 37, 37, 12, 12, 12, 12, 24, 24, 37, 62), (279, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), (226, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), (226, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), (173, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), (173, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), (0, 68, 196, 196, 196, 196, 147, 147, 86, 49, 49, 49, 37), (4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4), (0, 14, 24, 24, 24, 24, 24, 24, 24, 24, 24, 12, 12))


POSITION_COLUMNS = (0, 1, 3, 2, 4, 5, 7, 6, 8, 10, 9, 11, 12)


def rating(parameters, position=None, boosts=None):
    if len(parameters) != 147:
        raise ValueError('Native overall requires 147 parameters')
    position = parameters[0] if position is None else position
    if type(position) is not int or not 0 <= position < 13:
        raise ValueError('Invalid native position')
    position = POSITION_COLUMNS[position]
    values = [parameters[index] for index in PARAMETERS]
    if any(type(n) is not int or not 0 <= n <= 255 for n in values):
        raise ValueError('Invalid native rating parameters')
    values[0] -= 111
    values[26] = (values[26] * 59) // 3 + 40
    boosts = boosts or {}
    score = sum(weights[position] * max(15, min(95, max(0, value - 25) + boosts.get(index, 0)))
                for weights, index, value in zip(WEIGHTS, PARAMETERS, values))
    return max(40, (score + 500) // 1000)


ENGINE_CHECKS = (('weights', 13463920, 1456, '34d08a4df83cc1a8f224f3545df64c5f7f90c8db5d384c553d68e1b4548f4d76'), ('position_columns', 12833252, 52, '4c01face86873062acc196a339ecad0364eea3f22464026fddbabdbaa7daee61'), ('main_to_flat', 13463688, 48, '46cfa66762b058b23547f8ed67e95939ad8ce68d158e0c5ccf069091f304d66b'), ('flat_parameters', 13463788, 112, '946ee86c4a62ff917cad6e9dc079c59739ceddc2bebd543107676645389b4c57'), ('individual_kernel', 137041796, 1264, 'f900a9d6edced38bf2c18c911ee37c375fba99a9a5e4d844860991db18ee82b7'), ('team_kernel', 118104868, 340, '01f1ea3e84ac8ed229e5d4d4bf90c1fd5c84712d7beeb2a9a73a245da100f880'), ('manager_factor', 137052104, 296, '239d89d31ae20fd92ac7d1b8f72e07be483d696b33bfc3d468802140e1dd2aea'))


def verify_engine(stream):
    import hashlib
    for name, offset, size, expected in sorted(ENGINE_CHECKS, key=lambda row: row[1]):
        stream.seek(offset)
        data = stream.read(size)
        if len(data) != size or hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('原生评分关键逻辑已变化（' + name + '），无法确认 AI 强度门槛，请重新适配该包')
    return {'native_integer_rating_verified': True, 'critical_regions': len(ENGINE_CHECKS),
            'full_engine_fingerprint_required': False, 'actual_client_strength_measured': False}
