import itertools
from constants import *
from players import Players
from math import log10, ceil
from util import escape_suits, Dict2Class
from jinja2 import Template
from print import *
from deal import Deal
from imps import imps
from statistics import mean
from tourney_db import TourneyDB


class ResultGetter:
    _conn = None
    _deals = None

    def __init__(self, boards, pairs, tournament_id=None):
        self.boards = boards
        self.pairs = pairs
        self.tournament_id = tournament_id
        self.travellers = []
        self.totals = []
        self.personals = []
        self.names = []

    @property
    def conn(self):
        if self._conn is None:
            self._conn = TourneyDB.connect()
        return self._conn

    @property
    def cursor(self):
        return self.conn.cursor()

    @property
    def max_mp(self):
        return self.pairs - 2 - self.pairs % 2

    @property
    def deals(self):
        if not self._deals:
            self._deals = [Deal(raw_hands=h) for h in self.hands]
        return self._deals

    def get_names(self):
        cur = self.cursor
        cur.execute("select * from names order by number")
        raw = cur.fetchall()
        try:
            players = Players.get_players()
            for raw_pair in raw:
                self.names.append(Players.lookup(raw_pair[1], players))
        except:
            for i, raw_pair in enumerate(raw):
                if i >= len(self.names):
                    self.names.append((raw_pair[1].split(" "), 0, 1.6))
        if not raw:
            self.names = [(f"{i}_1", f"{i}_2") for i in range(1, self.pairs + 1)]
        self._conn = self.conn.close()

    def get_hands(self):
        self.hands = []
        cur = self.cursor
        cur.execute(f"select distinct * from boards order by number")
        # board #0 can be erroneously submitted
        self.hands = [h for h in cur.fetchall() if h[0]]

    def set_scores_ximp(self, board, scores, adjusted_scores):
        for s in adjusted_scores:
            mp_ns = 0 if s[3] == 'A/A' else 3 * (-1) ** ('A+/A-' == s[3])
            mp_ew = -mp_ns
            s[8] = mp_ns
            s[9] = mp_ew
            statement = f"update protocols set mp_ns={mp_ns}, mp_ew={mp_ew} where number={board} and ns={s[1]}"
            self.cursor.execute(statement)
        for s in scores:
            mp_ns = sum(imps(s[7] - other[7]) for other in scores) / (len(scores) - 1)
            mp_ew = -mp_ns
            if abs(mp_ns) < 1/len(scores):
                mp_ns = mp_ew = 0
            statement = f"update protocols set mp_ns={mp_ns}, mp_ew={mp_ew} where number={board} and ns={s[1]}"
            s[8] = mp_ns
            s[9] = mp_ew
            self.cursor.execute(statement)
        return scores

    def set_scores_imp(self, board, scores, adjusted_scores):
        for s in adjusted_scores:
            mp_ns = 0 if s[3] == 'A/A' else 3 * (-1) ** ('A+/A-' == s[3]) * (len(scores) - 1)
            mp_ew = -mp_ns
            s[8] = mp_ns
            s[9] = mp_ew
            statement = f"update protocols set mp_ns={mp_ns}, mp_ew={mp_ew} where number={board} and ns={s[1]}"
            self.cursor.execute(statement)
        if scores:
            tables = len(scores)
            index = tables * CONFIG["imp"]["outliers_percentile"] / 100
            fractional = CONFIG["imp"]["fractional"]
            sorted_results = list(sorted(s[7] for s in scores))
            weights = [0 if i + 1 < index or tables - i < index else 1 for i in range(len(scores))]
            if fractional and tables > 2:
                partial = int(index)
                weights[partial] = weights[-1 - partial] = 1 - index % 1
            results_mean = mean(w * r for w, r in zip(weights, sorted_results))
        else:
            results_mean = 0
        # datums ending in 5 are rounded towards the even number of tens
        # to make mean rounding error for a whole area tend to 0
        if results_mean % 20 == 5:
            datum = round(results_mean, -1) - 10
        else:
            datum = round(results_mean, -1)
        for s in scores:
            mp_ns = imps(s[7] - datum)
            mp_ew = -mp_ns
            statement = f"update protocols set mp_ns={mp_ns}, mp_ew={mp_ew} where number={board} and ns={s[1]}"
            s[8] = mp_ns
            s[9] = mp_ew
            self.cursor.execute(statement)
        return scores

    def set_scores_mp(self, board, scores, adjusted_scores):
        for s in adjusted_scores:
            mp_ns = round(self.max_mp / 100 * int(s[3].split("/")[0]), 1)
            mp_ew = round(self.max_mp / 100 * int(s[3].split("/")[1]), 1)
            s[8] = mp_ns
            s[9] = mp_ew
            statement = f"update protocols set mp_ns={mp_ns}, mp_ew={mp_ew} where number={board} and ns={s[1]}"
            self.cursor.execute(statement)
        scores.sort(key=lambda x: x[7])
        current = 0
        cluster_index = 0
        scores = [list(s) for s in scores]
        for s in scores:
            repeats = [s2[7] for s2 in scores].count(s[7])
            if adjusted_scores and CONFIG["mp"]["neuberg"]:
                mp_ew = (self.max_mp - 2 * len(adjusted_scores) - current - (repeats - 1) + 1) \
                        * (len(scores) + len(adjusted_scores)) / len(scores) - 1
                mp_ns = self.max_mp - mp_ew
            else:
                mp_ns = current + (repeats - 1)
                mp_ew = self.max_mp - mp_ns
            if cluster_index == repeats - 1:
                current += 2 * repeats
                cluster_index = 0
            else:
                cluster_index += 1
            statement = f"update protocols set mp_ns={mp_ns}, mp_ew={mp_ew} where number={board} and ns={s[1]}"
            s[8] = mp_ns
            s[9] = mp_ew
            self.cursor.execute(statement)
        return scores

    def get_results(self):
        """
        For adjustments refer to
        http://db.eurobridge.org/repository/departments/directing/2001Course/LecureNotes/Score%20Adjustments1.pdf
        """
        cur = self.cursor
        self.travellers = []
        for board in range(1, self.boards + 1):
            cur.execute(f"select * from protocols where number={board}")
            filtered = {}
            for protocol in cur.fetchall():
                unique_id = protocol[1] * (self.pairs + 1) + protocol[2]
                filtered[f"{unique_id}"] = protocol
            if len(filtered) != self.pairs // 2:
                print(f"Missing results for board #{board}")
            sorted_results = [list(f) for f in filtered.values()]
            adjusted_scores = [s for s in sorted_results if s[7] == 1]
            scores = [s for s in sorted_results if s[7] != 1]
            scoring_method = {
                "MPs": self.set_scores_mp,
                "IMPs": self.set_scores_imp,
                "Cross-IMPs": self.set_scores_ximp
            }[CONFIG["scoring"]]
            scores = scoring_method(board, scores, adjusted_scores)
            # TODO: change 60/40 to session average
            all_scores = sorted(scores + adjusted_scores, key=lambda x: x[-2])
            self.travellers.append([[s[1], s[2], escape_suits(s[3] + s[6]), s[4], escape_suits(s[5]),
                                     s[7] if s[7] >= 0 and s[7] != 1 else "",
                                    -s[7] if s[7] <= 0 else "", round(s[8], 2), round(s[9], 2)] for s in all_scores])
        self.conn.commit()

    def get_standings(self):
        max_mp = self.pairs - 2 - self.pairs % 2
        cur = self.cursor
        for pair in range(1, self.pairs + 1):
            cur.execute(f"select * from protocols where (ns={pair} or ew={pair}) and number > 0 order by number")
            # records are duplicated sometimes
            history = list(set(cur.fetchall()))
            results = [record[-2] if pair == record[1] else record[-1] for record in history]
            result_in_mp = sum(results)
            mp_per_board = result_in_mp/len(results)
            self.totals.append([pair, result_in_mp, mp_per_board])

            vul = {'-': "-", "n": "NS", "e": "EW", "b": "ALL"}
            self.personals.append([])
            for i in range(1, self.boards + 1):
                try:
                    board = [b for b in history if b[0] == i][0]
                except IndexError:
                    # ADDING NOT PLAYED
                    self.personals[-1].append([i, vul[VULNERABILITY[i % 16]], "-",
                                               "NOT PLAYED", "", "",
                                               0,
                                               0, 0, 0])
                    continue

                if pair == board[1]:
                    position = "NS"
                elif pair == board[2]:
                    position = "EW"
                self.personals[-1].append([board[0], vul[VULNERABILITY[board[0] % 16]], position,
                                          escape_suits(board[3] + board[6]), board[4], escape_suits(board[5]),
                                          board[7] * (-1) ** (pair != board[1]),
                                          board[8 + (pair != board[1])],
                                          round(board[8 + (pair != board[1])] * 100 / max_mp, 2),
                                          board[1 + (pair == board[1])]])
        self.totals.sort(key=lambda x: -x[2])
        try:
            self.get_masterpoints()
        except:
            for i in range(self.pairs):
                self.totals[i].append(0)
                self.totals[i].append(0)
            self.names = [[n[0] for n in p] for p in self.names]

    def get_masterpoints(self):
        n = self.pairs
        d = self.boards - self.travellers.count([])
        if AM:
            # AM
            # 52 is the number of cards in a board (sic!)
            total_rating = sum(sum(a[1] for a in p) / len(p) * 2 for p in self.names)

            played_boards = max(len([p for p in personal if p[3] != "NOT PLAYED"]) for personal in self.personals)
            b0 = total_rating * played_boards / 52 * CONFIG["tourney_coeff"]
            mps = [b0]
            for i in range(2, n):
                mps.append(b0 / (1 + i/(n - i)) ** (i - 1))
            mps.append(0)
            cluster_index = 0
            half = self.max_mp / 2 if CONFIG["scoring"] == "MPs" else 0
            for i in range(n):
                cluster_first = i - cluster_index
                if cluster_first + 1 > round(0.4 * n) or self.totals[i][2] < half:
                    self.totals[i].append(0)
                    continue
                cluster_length = len([a for a in self.totals if a[2] == self.totals[i][2]])
                cluster_total = sum(mps[j] for j, a in enumerate(self.totals) if a[2] == self.totals[i][2])\
                    / cluster_length
                if i + 1 < len(self.totals) and self.totals[i + 1][2] == self.totals[i][2]:
                    cluster_index += 1
                else:
                    cluster_index = 0
                # Ask Artem for the reasoning behind this
                if cluster_first + cluster_length > round(0.4 * n):
                    rounding_method = ceil
                else:
                    rounding_method = round
                self.totals[i].append(rounding_method(cluster_total))
        else:
            for t in self.totals:
                t.append(0)
        # RU
        # this dragon poker rules are taken from https://www.bridgesport.ru/materials/sports-classification/

        # Use maximum possible number of boards played by a certain pair.
        # The logic will change soon according to Dobrin.
        # Yet classification 4.1 looks like we shouldn't be recalculating it as of 2023.
        d = max(len([p for p in personal if p[3] != "NOT PLAYED"]) for personal in self.personals)
        ranks_ru = [sum(a[2] for a in p) / len(p) for p in self.names]
        team = "team" in CONFIG["scoring"].lower()
        n0 = n * (1 + team)  # number of pairs for team events also
        kp = 0.9 if team else 0.95
        typ = 2 - team
        q1 = list(sorted((0.2 - 0.12 * r if r < 0 else 0.2 / (1.6 ** r) for r in ranks_ru), key=lambda x: -x))
        q2 = [q * kp ** i for i, q in enumerate(q1)]
        last = 16 if type == 2 else 32
        kq = sum(q2[:last]) / 2 ** (typ - 1)
        kq1 = 1 if kq >= 1 else 1 - 0.7 * log10(kq)
        kqn = 0.6 * (kq + log10(n0) - 1.5) * kq1 if n0 >= 32 else 0.4 * kq * log10(n0) * kq1
        kd = 2.2 * log10(d) - 2
        t = n / 8 * max(0.5, 3 + kq - 0.5 * log10(n))
        r = 1.1 * (100 * kd * kqn) ** (1 / t)
        mps = [50 * kqn * kd / r ** i for i in range(self.pairs)]
        try:
            for i, t in enumerate(self.totals):
                cluster_length = len([a for a in self.totals if a[2] == self.totals[i][2]])
                tied_mps = [mps[j] for j, a in enumerate(self.totals) if a[2] == self.totals[i][2]]
                cluster_total = sum(tied_mps) / cluster_length
                t.append(1 if min(tied_mps) < 0.5 and max(map(round, tied_mps)) > 0 and cluster_total < 0.5
                         else round(cluster_total))
        except Exception:
            for i, t in enumerate(self.totals):
                t.append(0)
        # remove extra stuff from names
        self.names = [[n[0] for n in p] for p in self.names]

    @staticmethod
    def _replace(string):
        minus = '−'
        if type(string) == list:
            string = " & ".join(string)
            return string
        elif type(string) != str:
            return string
        string = string.replace("-", minus)
        return string

    def pdf_rankings(self):
        totals = []
        for i, rank in enumerate(self.totals):
            cluster = [i for i, r in enumerate(self.totals) if r[2] == rank[2]]
            repl_dict = {
                "rank": i + 1 if len(cluster) == 1 else f"{cluster[0] + 1}-{cluster[-1] + 1}", "number": rank[0],
                "names": self.names[int(rank[0]) - 1], "mp": round(rank[1], 2),
                "percent": round(100 * rank[2]/self.max_mp, 2),
                "masterpoints": rank[3] or "",
                "masterpoints_ru": rank[4] or ""
            }
            totals.append(Dict2Class({k: self._replace(v) for k, v in repl_dict.items()}))
        self.rankings_dict = {"AM": AM, "scoring": CONFIG['scoring'], "max": self.max_mp, "tables": self.pairs // 2,
                              "date": date if DEBUG else time.strftime("%Y-%m-%d"), "boards": self.boards,
                              "tournament_title": CONFIG["tournament_title"], "totals": totals}
        html_string = Template(open("templates/rankings_template.html").read()).render(**self.rankings_dict)
        return print_to_pdf(html_string, "Ranks.pdf")

    def pdf_travellers(self, boards_only=False):
        boards = []
        scoring_short = CONFIG["scoring"].rstrip("s").replace("Cross-", "X")
        for board_number in range(1, self.boards + 1):
            deal = self.deals[board_number - 1]
            if not boards_only:
                res = self.travellers[board_number - 1]
            # Dealer and vul improvements
            repl_dict = {"d": deal.data["d"].upper(), "b": board_number, "v": deal.data["v"]}
            for i, h in enumerate(hands):
                for j, s in enumerate(SUITS):
                    repl_dict[f"{h}{s}"] = deal.data[f"{h}{s}"].upper().replace("T", "10")
                for j, d in enumerate(DENOMINATIONS):
                    repl_dict[f"{h}_par_{d}"] = deal.data[f"{h}_par_{d}"]
            for key in ('level', 'denomination', 'declarer', 'score', 'minimax_url', 'result'):
                repl_dict[key] = deal.data[key]
            if repl_dict['denomination'] == "n":
                repl_dict['denomination'] = "NT"
            else:
                repl_dict['denomination'] = repl_dict['denomination'].upper()
            level = deal.data['level']
            den = deal.data['denomination']
            decl = deal.data['declarer']
            result = deal.data['result']
            score = deal.data['score']
            repl_dict['minimax_contract'] = f"{level}{den} {decl}" if level else "PASS"
            repl_dict['minimax_outcome'] = f"{result}, {score}" if level else ""

            dealer_low = repl_dict["d"].lower()
            repl_dict["ns_vul"] = (deal.data["v"] in ("EW", "-")) * "non" + "vul"
            repl_dict["ew_vul"] = (deal.data["v"] in ("NS", "-")) * "non" + "vul"
            repl_dict[f"{dealer_low}_dealer"] = "dealer"
            # VUL in boards
            boards.append(Dict2Class({k: self._replace(v) for k, v in repl_dict.items()}))
            if boards_only:
                continue
            boards[-1].tables = []
            for r in res:
                repl_dict = {k: str(v).upper() for k, v in zip(
                    ("ns", "ew", "contract", "declarer", "lead"), r)}
                repl_dict["nsplus"] = r[5]
                repl_dict["nsminus"] = r[6]
                repl_dict["mp_ns"] = round(r[7], 2)
                repl_dict["mp_ew"] = round(r[8], 2)
                repl_dict["ns_name"] = self.names[r[0] - 1]
                repl_dict["ew_name"] = self.names[r[1] - 1]
                repl_dict["bbo_url"] = deal.url_with_contract(r[2][0], r[2].split("=")[0].split("+")[0].split("-")[0][1:], r[3])
                boards[-1].tables.append(Dict2Class({k: self._replace(v) for k, v in repl_dict.items()}))

        self.travellers_dict = {"scoring_short": scoring_short, "boards": boards}
        html_string = Template(open("templates/travellers_template.html").read()).render(**self.travellers_dict)

        return print_to_pdf(html_string, "Travellers.pdf")

    @staticmethod
    def _suits(string):
        old_string = string
        for s in ["spade", "heart", "diamond", "club"]:
            string = re.sub('([1-7])' + s[0], f'\g<1><img src="https://bridgemoscow.ru/images/{s}.gif"/>', string, flags=re.IGNORECASE)
            if old_string != string:
                break
            string = re.sub(s[0]+'([1-9akqjt]0?)', f'<img src="https://bridgemoscow.ru/images/{s}.gif"/>\g<1>', string, flags=re.IGNORECASE)
            if old_string != string:
                break
        else:
            string = string.replace("n", "NT")
        return string

    @staticmethod
    def suspicious_result(deal, board_data):
        if board_data[3].lower() not in ("pass", "not played") and '/' not in board_data[3]:
            level = board_data[3][0]
            denomination = board_data[3][1].lower()
            declarer = board_data[4].lower()
            dummy = hands[(hands.index(declarer) + 2) % 4]
            result = board_data[3].lower()[-2:].lstrip("sdhcnx")
            tricks = int(level) + 6 if result == "=" else eval(f'{level}{result}') + 6
            par = deal.data[f"{declarer}_par_{denomination}"]
            if denomination != "n":
                decl_trumps = len(deal.data.get(f"{declarer}{denomination}"))
                dummy_trumps = len(deal.data.get(f"{dummy}{denomination}"))
                # 5-0 is good, 4-1 or 3-2 or less are not
                if decl_trumps + dummy_trumps <= 5 and abs(decl_trumps - dummy_trumps) < 5:
                    return True
                fit = decl_trumps + dummy_trumps
            else:
                fit = 13

            if (abs(tricks - par) > 3 and denomination == "n") or (abs(tricks - par) >= 3 and fit < 7):
                if tricks > par:
                    try:
                        # check if lead gives decl that number of trick
                        on_lead = hands[(hands.index(declarer) + 1) % 4]
                        hand = itertools.chain(
                            *([f'{s}{c}' for c in deal.data[f'{on_lead}{s}'].replace('10', 't')] for s in SUITS))
                        lead_as_written = board_data[5].lower().replace('10', 't')
                        if lead_as_written:
                            lead_suit = lead_as_written[0]
                            if lead_as_written[1] in deal.data[f"{on_lead}{lead_suit}"]:
                                # lead is written correctly
                                tricks_after_lead = deal.tricks_after_lead(denomination, on_lead, lead_as_written)
                                return tricks_after_lead is None or tricks > tricks_after_lead
                            else:
                                # hope that at least suite is written correctly
                                tricks_after_lead = [deal.tricks_after_lead(denomination, on_lead, card)
                                                     for card in hand if card.startswith(lead_suit)]
                                return not (tricks_after_lead and
                                    any(tricks >= t for t in tricks_after_lead if t is not None))
                        else:
                            # no lead available
                            tricks_after_lead = [deal.tricks_after_lead(denomination, on_lead, card) for card in hand]
                            # if at least 3 cards of the leading hand give declarer at least what they got, it's OK
                            return len([t for t in tricks_after_lead if t is not None and tricks <= t]) < 2
                    except Exception:
                        # TODO: remove
                        pass
                return True
        return False

    def pdf_scorecards(self):
        scoring_short = CONFIG["scoring"].rstrip("s").replace("Cross-", "X")
        boards_per_round_candidates = []
        for res in self.personals:
            opps = [r[-1] for r in res]
            boards_per_round_candidates.extend(sum(1 for _ in group) for _, group in itertools.groupby(opps))
        boards_per_round = max(set(boards_per_round_candidates), key=boards_per_round_candidates.count)
        num_of_rounds = self.boards // boards_per_round
        totals = self.totals
        self.scorecards_dict = {
            "scoring_short": scoring_short, "colspan": 9 + (CONFIG["scoring"] == "MPs"),
            "boards_per_round": boards_per_round, "pairs": []
        }
        #TODO: handle incomplete howell
        max_mp = self.max_mp * len([p for p in self.personals[0] if p[3] != "NOT PLAYED"])

        for pair_number, results in enumerate(self.personals):
            pair_rank = [t for t in totals if t[0] == pair_number + 1][0]
            self.scorecards_dict["pairs"].append(Dict2Class({"name": self._replace(self.names[pair_number]), "number": pair_number + 1,
                            "mp_total": round(pair_rank[1], 2), "max_mp": max_mp,
                            "percent_total": round(100 * pair_rank[1] / max_mp, 2),
                            "rank": totals.index(pair_rank) + 1, "boards": []
                            }))
            for r in range(num_of_rounds):
                mp_for_round = sum(results[r * boards_per_round + b][7] for b in range(boards_per_round))
                for i in range(boards_per_round):
                    board_data = results[r * boards_per_round + i]
                    deal = self.deals[r * boards_per_round + i]
                    suspicious = self.suspicious_result(deal, board_data)
                    if board_data[3] == "NOT PLAYED":
                        opp_names = ""
                    else:
                        opp_names = self.names[board_data[-1] - 1]
                    dikt = {"number": board_data[0], "vul": board_data[1],
                            "dir": board_data[2], "contract": self._suits(board_data[3]),
                            "declarer": board_data[4].upper(), "lead": self._suits(board_data[5]),
                            "score": board_data[6] if board_data[6] != 1 else '', "mp": round(board_data[7], 2),
                            "percent": round(board_data[8], 2),
                            "mp_per_round": round(mp_for_round, 2),
                            "opp_names": opp_names, "suspicious": "suspicious" * suspicious}
                    self.scorecards_dict["pairs"][-1].boards.append(Dict2Class(
                       {k: self._replace(v) for k, v in dikt.items()}))
        html_template = Template(open("templates/scorecards_template.html").read()).render(**self.scorecards_dict)
        try:
            return print_to_pdf(html_template, "Scorecards.pdf")
        except:
            pass

    def save(self, tourney_exists=False, correction=False):
        conn = Players.connect()
        cursor = conn.cursor()
        title = self.rankings_dict['tournament_title']
        scoring = self.rankings_dict['scoring']
        max_mp = self.scorecards_dict["pairs"][0].max_mp
        boards_per_round = [p[-1] for p in self.personals[0]].count(self.personals[0][0][-1])
        if not self.tournament_id:
            cursor.execute(f'select count(*) from tournaments')
            self.tournament_id = cursor.fetchone()[0] + 1
        if correction:
            cursor.execute(f'delete from tournaments where tournament_id={self.tournament_id}')
            cursor.execute(f'delete from names where tournament_id={self.tournament_id}')
            cursor.execute(f'delete from boards where tournament_id={self.tournament_id}')
            cursor.execute(f'delete from protocols where tournament_id={self.tournament_id}')

        num_of_rounds = self.boards // boards_per_round
        if not tourney_exists:
            t_date = date if DEBUG else time.strftime("%Y-%m-%d")
            insert = f"""INSERT INTO tournaments (date, boards, players, max, scoring, tournament_id, title, rounds) VALUES 
    ('{t_date}', {self.boards}, {self.pairs}, {max_mp}, '{scoring}', {self.tournament_id}, '{title}', {num_of_rounds});"""
            cursor.execute(insert)
        for pair in self.rankings_dict["totals"]:
            rows = f"({self.tournament_id}, {pair.number}, '{pair.names}', '{self._replace(pair.rank)}', {pair.mp}, {pair.percent}," \
                   f"{pair.masterpoints or 0}, {pair.masterpoints_ru or 0})"
            insert = f"""
INSERT INTO names (tournament_id, number, partnership, rank, mps, percent, masterpoints, masterpoints_ru) 
VALUES {rows};"""
            cursor.execute(insert)
        hands_columns = ["".join(p) for p in itertools.product(hands, SUITS)]
        par_columns = ["_par_".join(p) for p in itertools.product(hands, reversed(DENOMINATIONS))]
        for b in self.travellers_dict["boards"]:
            hand_values = "'" + "', '".join(str(b.__getattribute__(h)) for h in hands_columns) + "'"
            par_values = "'" + "', '".join(str(b.__getattribute__(h)) for h in par_columns) + "'"
            rows = f"({self.tournament_id}, {b.b}, {hand_values}, {par_values}, '{self._suits(b.minimax_contract)}', " \
                   f"'{self._replace(b.minimax_outcome)}', '{b.minimax_url}')"
            insert = f"""INSERT INTO boards (tournament_id, number, {", ".join(hands_columns)},
{", ".join(par_columns)}, minimax_contract, minimax_outcome, minimax_url) VALUES {rows};"""
            cursor.execute(insert)
            for t in b.tables:
                rows = f"({self.tournament_id}, {b.b}, {t.ns}, {t.ew}, '{self._suits(t.contract)}', '{t.declarer}', " \
                       f"'{self._suits(t.lead)}', {self._replace(t.nsplus or -int(t.nsminus or 0))}, {self._replace(t.mp_ns)}," \
                       f"{self._replace(t.mp_ew)}, '{t.bbo_url}')"
                insert = f"""INSERT INTO protocols (tournament_id, number, ns, ew, contract, declarer, lead,
score, mp_ns, mp_ew, handviewer_link) VALUES {rows};"""
                cursor.execute(insert)
        conn.commit()
        conn.close()

    def boards_only(self):
        self.get_hands()
        return self.pdf_travellers(boards_only=True)

    def process(self):
        paths = []
        self.get_results()
        self.get_names()
        self.get_hands()
        self.get_standings()
        paths.append(self.pdf_rankings())
        paths.append(self.pdf_travellers())
        paths.append(self.pdf_scorecards())
        self.conn.close()
        return paths


if __name__ == "__main__":
    g = ResultGetter(28, 8)
    CONFIG["scoring"] = "MPs"
    g.process()
    # TourneyDB.to_access(800)
    g.save()
