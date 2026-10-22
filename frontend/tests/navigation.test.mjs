import { test } from "node:test";
import assert from "node:assert/strict";
import { selectedLeague, leaguePath, competitions } from "../src/navigation.ts";
test("existing EPL URLs remain compatible", () => {
  assert.equal(selectedLeague(""), "epl");
  assert.equal(leaguePath("/teams/1", "epl"), "/teams/1");
});
test("La Liga persists through team, results, method, and return links", () => {
  for (const path of ["/", "/teams/52", "/teams/53", "/method"]) {
    const url = leaguePath(path, "laliga");
    assert.equal(
      selectedLeague(new URL(url, "http://localhost").search),
      "laliga",
    );
    assert.equal(leaguePath(url, "epl"), path);
  }
});
test("league selection survives filters and deep links", () => {
  assert.equal(selectedLeague("?q=Real&league=laliga&sort=value"), "laliga");
  assert.equal(
    leaguePath("/?q=Real&sort=value", "laliga"),
    "/?q=Real&sort=value&league=laliga",
  );
  assert.equal(leaguePath("/?league=laliga&q=Arsenal", "epl"), "/?q=Arsenal");
});
test("only the five requested competitions are exposed", () => {
  assert.deepEqual(Object.keys(competitions), [
    "epl",
    "laliga",
    "seriea",
    "bundesliga",
    "ligue1",
  ]);
  assert.equal(selectedLeague("?league=eredivisie"), "epl");
});

test("all five leagues preserve team, method, filters and return navigation", () => {
  for (const league of Object.keys(competitions)) {
    for (const path of ["/", "/teams/72", "/method", "/?q=Paris&sort=value"]) {
      const url = leaguePath(path, league);
      assert.equal(
        selectedLeague(new URL(url, "http://localhost").search),
        league,
      );
      assert.equal(leaguePath(url, "epl"), path);
    }
  }
  assert.equal(selectedLeague("?league=__proto__"), "epl");
});
