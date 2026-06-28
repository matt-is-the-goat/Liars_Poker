/* Liar's Poker, Balatro-style browser client. */
const socket = io();
const $ = (id) => document.getElementById(id);

const RANKS = [
  [2, "2"], [3, "3"], [4, "4"], [5, "5"], [6, "6"], [7, "7"], [8, "8"],
  [9, "9"], [10, "10"], [11, "J"], [12, "Q"], [13, "K"], [14, "A"],
];
const SUIT_GLYPH = { S: "♠", H: "♥", D: "♦", C: "♣" };
const SUIT_ORDER = { S: 0, H: 1, D: 2, C: 3 };
const PERSONA_EMOJI = { trusting: "😇", balanced: "🤖", liar: "😈" };

const CATEGORY_FIELDS = {
  HIGH_CARD: { rank: "Rank" },
  PAIR: { rank: "Rank" },
  TWO_PAIR: { rank: "High pair", rank2: "Low pair" },
  TRIPS: { rank: "Rank" },
  STRAIGHT: { rank: "A rank it contains" },
  FLUSH: { rank: "High card", suit: true, minRank: 6 },
  FULL_HOUSE: { rank: "Three of", rank2: "Pair of" },
  QUADS: { rank: "Rank" },
  MANSION: { rank: "Four of", rank2: "Three of" },
  STRAIGHT_FLUSH: { rank: "A rank it contains", suit: true },
  QUINTS: { rank: "Rank" },
  SEXES: { rank: "Rank" },
  HOTEL: { rank: "Five of", rank2: "Four of" },
};

let myTurn = false;
let myHand = [];
let sortMode = "rank";
let botMeta = {};       // index -> {personality, difficulty}
let latestView = null;
let lastCanChallenge = false;
let roundBids = {};      // index -> latest bid text this round
let activeBidder = null; // index of the standing (current) bid

/* ---------- card rendering ---------- */
function makeCardEl(c) {
  const el = document.createElement("div");
  if (c.is_joker) {
    el.className = "card joker";
    el.innerHTML = `<span class="pip">🃏</span>`;
    return el;
  }
  const red = c.suit === "H" || c.suit === "D";
  const g = SUIT_GLYPH[c.suit] || "";
  el.className = "card" + (red ? " red" : "");
  el.innerHTML =
    `<span class="corner tl">${c.rank}<br>${g}</span>` +
    `<span class="pip">${g}</span>` +
    `<span class="corner br">${c.rank}<br>${g}</span>`;
  return el;
}

function makeCardBack() {
  const el = document.createElement("div");
  el.className = "card-back";
  return el;
}

function renderFan(el, cards) {
  el.innerHTML = "";
  const n = cards.length;
  cards.forEach((c, i) => {
    const card = makeCardEl(c);
    const off = i - (n - 1) / 2;
    card.style.setProperty("--rot", (off * 5).toFixed(2) + "deg");
    card.style.setProperty("--dip", (Math.abs(off) * 7).toFixed(1) + "px");
    card.style.zIndex = i;
    el.appendChild(card);
  });
}

/* ---------- hand sorting ---------- */
function sortHand(cards) {
  const arr = cards.slice();
  arr.sort((a, b) => {
    if (a.is_joker !== b.is_joker) return a.is_joker ? 1 : -1; // jokers last
    if (sortMode === "suit" && a.suit !== b.suit) {
      return SUIT_ORDER[a.suit] - SUIT_ORDER[b.suit];
    }
    return b.value - a.value; // high -> low
  });
  return arr;
}

function renderHand() {
  renderFan($("hand"), sortHand(myHand));
}

/* ---------- seats ---------- */
function renderSeats(view, revealByIndex) {
  const wrap = $("seats");
  wrap.innerHTML = "";
  for (const p of view.players) {
    if (p.is_you) continue;
    const meta = botMeta[p.index] || {};
    const seat = document.createElement("div");
    seat.className = "seat";
    const reveal = revealByIndex && revealByIndex[p.index];
    if (p.eliminated) seat.classList.add("eliminated");
    if (!reveal && p.index === activeBidder) seat.classList.add("active");
    if (reveal && reveal.is_loser) seat.classList.add("loser");

    const emoji = PERSONA_EMOJI[meta.personality] || "🤖";
    const badge = meta.personality
      ? `${meta.personality} · ${meta.difficulty}` : "";

    const stack = document.createElement("div");
    stack.className = "seat-stack";
    if (reveal) {
      for (const c of reveal.cards) stack.appendChild(makeCardEl(c));
    } else if (!p.eliminated) {
      for (let k = 0; k < p.card_count; k++) stack.appendChild(makeCardBack());
    }

    seat.innerHTML =
      `<div class="seat-avatar">${emoji}</div>` +
      `<div class="seat-name">${p.name}</div>` +
      `<div class="seat-badge">${p.eliminated ? "out" : badge}</div>`;
    seat.appendChild(stack);

    if (!reveal && roundBids[p.index]) {
      const bubble = document.createElement("div");
      bubble.className = "seat-bid" + (p.index === activeBidder ? " standing" : "");
      bubble.textContent = roundBids[p.index];
      seat.appendChild(bubble);
    }
    wrap.appendChild(seat);
  }
}

function renderBanner() {
  const banner = $("bid-banner");
  if (activeBidder != null && roundBids[activeBidder] && latestView) {
    const who = latestView.players[activeBidder];
    banner.innerHTML = `${roundBids[activeBidder]} ` +
      `<span class="who">by ${who && who.is_you ? "you" : (who ? who.name : "")}</span>`;
  } else {
    banner.textContent = "No bid yet, you open";
  }
}

function resetRound() {
  roundBids = {};
  activeBidder = null;
}

function renderTable(view) {
  latestView = view;
  myHand = view.my_hand;
  activeBidder = view.current_bidder;
  renderSeats(view, null);
  renderBanner();
  renderHand();
}

/* ---------- showdown ---------- */
function renderShowdown(data) {
  const byIndex = {};
  for (const h of data.hands) byIndex[h.index] = h;
  if (latestView) renderSeats(latestView, byIndex);

  const loser = data.hands.find((h) => h.is_loser);
  const loserName = loser ? (loser.is_you ? "You" : loser.name) : "Someone";
  $("showdown-verdict").innerHTML =
    `<strong>${data.bid.text}</strong> ` +
    (data.existed ? `<span class="ok">existed ✓</span>` : `<span class="no">did NOT exist ✗</span>`) +
    `, ${loserName} loses`;
  renderFan($("showdown-pool"), data.pool);

  // Show the Next button only while we're still in the game; once eliminated the
  // server auto-advances bot-only rounds for us.
  const stillIn = data.hands.some((h) => h.is_you);
  const nextBtn = $("next-btn");
  nextBtn.classList.toggle("hidden", !stillIn);
  nextBtn.disabled = false;
  nextBtn.textContent = "Next hand ▶";

  $("bid-banner").classList.add("hidden");
  $("showdown").classList.remove("hidden");
  resetRound();  // clear bid bubbles for the next round
}

function hideShowdown() {
  $("showdown").classList.add("hidden");
  $("bid-banner").classList.remove("hidden");
}

/* ---------- log ---------- */
function log(message) {
  if (message.startsWith("All hands:") ||
      message.startsWith("Combined pool:") ||
      /^\s{2}.+:/.test(message)) {
    return;
  }
  const el = $("log");
  const line = document.createElement("div");
  if (/existed|did NOT exist|eliminated|wins the game/.test(message)) {
    line.className = "log-reveal";
  }
  line.textContent = message;
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

/* ---------- turn controls ---------- */
function setControlsEnabled(on, canChallenge) {
  myTurn = on;
  $("controls").classList.toggle("disabled", !on);
  $("challenge_btn").classList.toggle("hidden", !canChallenge);
  $("turn-status").textContent = on
    ? "Your move. Make a bid or call bullshit."
    : "Waiting for other players…";
}

function showError(msg) {
  const e = $("error");
  e.textContent = msg;
  e.classList.remove("hidden");
}

/* ---------- bid builder ---------- */
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
function refreshBidFields() {
  const spec = CATEGORY_FIELDS[$("category").value];
  fillRanks($("rank"), spec.minRank || 2);
  $("rank-field").childNodes[0].nodeValue = (spec.rank || "Rank") + " ";
  $("rank2-field").classList.toggle("hidden", !spec.rank2);
  if (spec.rank2) $("rank2-field").childNodes[0].nodeValue = spec.rank2 + " ";
  $("suit-field").classList.toggle("hidden", !spec.suit);
}
fillRanks($("rank"));
fillRanks($("rank2"));
$("category").addEventListener("change", refreshBidFields);
refreshBidFields();

/* ---------- socket events ---------- */
socket.on("game_started", (data) => {
  botMeta = {};
  for (const b of data.bots || []) botMeta[b.index] = b;
  resetRound();
  $("setup").classList.add("hidden");
  $("game").classList.remove("hidden");
  $("gameover").classList.add("hidden");
  hideShowdown();
  $("log").innerHTML = "";
  log(`Opponents: ${data.opponents.join(", ")}`);
});

socket.on("state", (data) => {
  hideShowdown();
  resetRound();  // new round, clear last round's bid bubbles
  renderTable(data.view);
});

socket.on("bid_made", (data) => {
  if (data.index == null) return;
  roundBids[data.index] = data.text;
  activeBidder = data.index;
  if (latestView) {
    renderSeats(latestView, null);
    renderBanner();
  }
});

socket.on("your_turn", (data) => {
  hideShowdown();
  renderTable(data.view);
  $("error").classList.add("hidden");
  lastCanChallenge = data.can_challenge;
  setControlsEnabled(true, data.can_challenge);
});

socket.on("log", (data) => log(data.message));
socket.on("round_result", (data) => renderShowdown(data));
socket.on("error", (data) => {
  // The move was rejected, so it's still our turn, so re-enable the controls.
  showError(data.message);
  setControlsEnabled(true, lastCanChallenge);
});

socket.on("game_over", (data) => {
  setControlsEnabled(false, false);
  $("winner-text").textContent =
    data.winner === "You" ? "🏆 YOU WIN!" : `${data.winner} wins`;
  $("gameover").classList.remove("hidden");
});

/* ---------- user actions ---------- */
$("start_btn").addEventListener("click", () => {
  socket.emit("start_game", {
    num_bots: +$("num_bots").value,
    start_count: +$("start_count").value,
    threshold: +$("threshold").value,
    num_jokers: +$("num_jokers").value,
    difficulty: $("difficulty").value,
    personality: $("personality").value,
  });
});

$("again_btn").addEventListener("click", () => {
  $("game").classList.add("hidden");
  $("setup").classList.remove("hidden");
});

$("sort-rank").addEventListener("click", () => { sortMode = "rank"; renderHand(); });
$("sort-suit").addEventListener("click", () => { sortMode = "suit"; renderHand(); });

$("log-toggle").addEventListener("click", () => {
  $("log-panel").classList.toggle("hidden");
});
$("log-close").addEventListener("click", () => {
  $("log-panel").classList.add("hidden");
});

$("next-btn").addEventListener("click", () => {
  const btn = $("next-btn");
  btn.disabled = true;
  btn.textContent = "Dealing…";
  socket.emit("continue_round");
});

$("bid_btn").addEventListener("click", () => {
  if (!myTurn) return;
  const spec = CATEGORY_FIELDS[$("category").value];
  const payload = { type: "bid", category: $("category").value, rank: +$("rank").value };
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
