/* Liar's Poker — browser client. Talks to the Flask/Socket.IO server. */
const socket = io();

const $ = (id) => document.getElementById(id);

const RANKS = [
  [2, "2"], [3, "3"], [4, "4"], [5, "5"], [6, "6"], [7, "7"], [8, "8"],
  [9, "9"], [10, "10"], [11, "J"], [12, "Q"], [13, "K"], [14, "A"],
];

// Which inputs each category needs. r2 = second rank, suit = suit picker.
const CATEGORY_FIELDS = {
  HIGH_CARD: { rank: "Rank" },
  PAIR: { rank: "Rank" },
  TWO_PAIR: { rank: "High pair", rank2: "Low pair" },
  TRIPS: { rank: "Rank" },
  STRAIGHT: { rank: "A rank it contains" },
  FLUSH: { rank: "High card", suit: true, minRank: 6 },
  FULL_HOUSE: { rank: "Three of", rank2: "Pair of" },
  QUADS: { rank: "Rank" },
  STRAIGHT_FLUSH: { rank: "A rank it contains", suit: true },
};

let myTurn = false;

// ---- rank dropdown population ----
function fillRanks(select, minRank = 2) {
  select.innerHTML = "";
  for (const [val, label] of RANKS) {
    if (val < minRank) continue;
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = label;
    select.appendChild(opt);
  }
}
fillRanks($("rank"));
fillRanks($("rank2"));

// ---- category -> visible fields ----
function refreshBidFields() {
  const spec = CATEGORY_FIELDS[$("category").value];
  const minRank = spec.minRank || 2;
  fillRanks($("rank"), minRank);
  $("rank-field").querySelector("label, span") ;
  $("rank-field").childNodes[0].nodeValue = (spec.rank || "Rank") + " ";
  $("rank2-field").classList.toggle("hidden", !spec.rank2);
  if (spec.rank2) $("rank2-field").childNodes[0].nodeValue = spec.rank2 + " ";
  $("suit-field").classList.toggle("hidden", !spec.suit);
}
$("category").addEventListener("change", refreshBidFields);
refreshBidFields();

// ---- rendering ----
function renderHand(cards) {
  const el = $("hand");
  el.innerHTML = "";
  for (const c of cards) {
    const d = document.createElement("div");
    d.className = "card" + (c.is_joker ? " joker" : (c.suit === "H" || c.suit === "D" ? " red" : ""));
    d.textContent = c.text;
    el.appendChild(d);
  }
}

function renderTable(view) {
  const ul = $("players");
  ul.innerHTML = "";
  for (const p of view.players) {
    const li = document.createElement("li");
    if (p.is_you) li.classList.add("you");
    if (p.eliminated) li.classList.add("eliminated");
    if (p.index === view.current_bidder) li.classList.add("bidder");
    const count = p.eliminated ? "out" : `${p.card_count} card${p.card_count === 1 ? "" : "s"}`;
    li.innerHTML = `<span>${p.is_you ? "You" : p.name}</span><span class="pc-count">${count}</span>`;
    ul.appendChild(li);
  }
  const banner = $("bid-banner");
  if (view.current_bid) {
    const who = view.players[view.current_bidder];
    banner.textContent = `Current bid: ${view.current_bid.text} (${who.is_you ? "you" : who.name})`;
  } else {
    banner.textContent = "No bid yet — you can open";
  }
}

function log(message) {
  const el = $("log");
  const line = document.createElement("div");
  if (/All hands:|Combined pool:|existed|did NOT exist/.test(message)) {
    line.className = "log-reveal";
  }
  line.textContent = message;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function setControlsEnabled(on, canChallenge) {
  myTurn = on;
  $("controls").classList.toggle("disabled", !on);
  $("challenge_btn").classList.toggle("hidden", !canChallenge);
  $("turn-status").textContent = on
    ? "Your move — make a bid or call bullshit."
    : "Waiting for other players…";
}

function showError(msg) {
  const e = $("error");
  e.textContent = msg;
  e.classList.remove("hidden");
}
function clearError() { $("error").classList.add("hidden"); }

// ---- socket events ----
socket.on("game_started", (data) => {
  $("setup").classList.add("hidden");
  $("game").classList.remove("hidden");
  $("gameover").classList.add("hidden");
  $("log").innerHTML = "";
  log(`Opponents: ${data.opponents.join(", ")}`);
});

socket.on("state", (data) => {
  renderHand(data.view.my_hand);
  renderTable(data.view);
});

socket.on("your_turn", (data) => {
  renderHand(data.view.my_hand);
  renderTable(data.view);
  clearError();
  setControlsEnabled(true, data.can_challenge);
});

socket.on("log", (data) => log(data.message));

socket.on("round_result", () => { /* narrated via log; hook for future animation */ });

socket.on("error", (data) => showError(data.message));

socket.on("game_over", (data) => {
  setControlsEnabled(false, false);
  $("winner-text").textContent =
    data.winner === "You" ? "🏆 You win!" : `Game over — ${data.winner} wins.`;
  $("gameover").classList.remove("hidden");
});

// ---- user actions ----
$("start_btn").addEventListener("click", () => {
  socket.emit("start_game", {
    num_bots: +$("num_bots").value,
    start_count: +$("start_count").value,
    threshold: +$("threshold").value,
    num_jokers: +$("num_jokers").value,
  });
});

$("again_btn").addEventListener("click", () => {
  $("game").classList.add("hidden");
  $("setup").classList.remove("hidden");
});

$("bid_btn").addEventListener("click", () => {
  if (!myTurn) return;
  const spec = CATEGORY_FIELDS[$("category").value];
  const payload = { type: "bid", category: $("category").value };
  payload.rank = +$("rank").value;
  if (spec.rank2) payload.rank2 = +$("rank2").value;
  if (spec.suit) payload.suit = $("suit").value;
  setControlsEnabled(false, false);
  socket.emit("submit_action", payload);
});

$("challenge_btn").addEventListener("click", () => {
  if (!myTurn) return;
  setControlsEnabled(false, false);
  socket.emit("submit_action", { type: "challenge" });
});
