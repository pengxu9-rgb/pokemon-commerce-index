"use strict";
const fs = require("node:fs");
const path = require("node:path");
if (process.argv.length !== 3) throw new Error("Provide the frontend checkout path");
const { validateCommerceResponse } = require(path.resolve(process.argv[2], "creator/src/lib/pokemon/commerceContract.cjs"));
const fixture = JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../examples/bns_url_preview_contracts.json"), "utf8"));
for (const name of ["ready", "choices", "refused"]) validateCommerceResponse("handoff", fixture[name]);
for (const refusal of fixture.refusals) validateCommerceResponse("handoff", { ...fixture.refused,
  status: refusal.status === "variant_selection_required" ? "variant_selection_required" : "manual_handoff_required",
  provider_result: refusal, quote_status: refusal.code, message: refusal.message });
console.log(JSON.stringify({ handoff_fixtures: 3, refusal_fixtures: fixture.refusals.length, passed: true }));
