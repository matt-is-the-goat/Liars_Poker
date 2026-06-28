# Liar's Poker

A card game we made up. Think Liar's Dice, but with poker hands and everyone's
cards pooled together. You bluff, you call people out, and the last one standing wins.

Right now you play against bots in the terminal. A web version (with real people)
is on the way.

## How to play

```
python main.py
```

It'll ask you a few setup questions (how many bots, how many cards, jokers, etc.),
deal you a hand, and away you go. Want the same game twice? Add a seed:

```
python main.py --seed 42
```

## The gist

Everyone gets some cards, face down. You can see your own hand and how many cards
everyone else is holding, just not *what* they're holding.

On your turn you do one of two things:

- **Make a bid.** Claim a poker hand exists somewhere in *everyone's* combined
  cards. Your bid has to beat the last one. First bid of the round can be anything,
  even a high card.
- **Call bullshit.** You don't buy the last claim, so everyone flips their cards.
  If the hand really is there, you lose the round. If it isn't, the bluffer does.

Lose a round and you pick up a card. Collect too many and you're out. Be the last
player left and you win the whole thing.

### Bids, weakest to strongest

high card, pair, two pair, three of a kind, straight, flush, full house, four of a
kind, straight flush.

A few of these have their own quirks:

- **Straights.** You name a rank the straight contains, like "a straight with a 6
  in it". Any straight covering that rank counts. To raise, name a higher rank.
- **Flushes.** You name the suit and the high card, like "ace-high hearts". Only
  cards at or below that rank count, and the card you named has to actually be
  there. To raise, go *lower*, since a queen-high flush is harder to make than an
  ace-high one.
- **Straight flushes.** Same idea as straights, but all one suit.

### Jokers

Optional, anywhere from 0 to 2 of them. A joker is a wildcard. When the cards come
up it turns into whatever card the claim needs. Two real 9s and a joker? That's
three 9s.

## The bots

Each bot has a personality and a difficulty:

- **Trusting.** Rarely calls bullshit, bids honestly.
- **Liar.** Bluffs constantly, almost never calls you out.
- **Balanced.** Plays it down the middle.

Difficulty (easy / medium / hard) controls how sharp their read on the odds is.
Under the hood they estimate the chance a bid is true by simulating thousands of
possible hands.

There's also an experimental "opponent modelling" toggle, where bots try to read
meaning into what others bid. Fun fact: in a game this built on lying, it actually
makes them play *worse*. Leave it off unless you want to watch bots get bluffed.

## What's next

- Web app so you can play real people
- A reinforcement-learning bot that teaches itself the game (and, hopefully, the
  right amount of suspicion)
