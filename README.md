# CS 432 - Assignment 4: Sharding of the Developed Application

## Project Objective
Implement logical data partitioning (sharding) across multiple simulated nodes/tables by selecting a suitable shard key, routing queries correctly, and analyzing scalability trade-offs.

## Core Technical Pipeline
- Shard Key Selection
- Data Partitioning
- Query Routing
- Scalability Analysis

## Sub-task 1: Shard Key Selection and Justification

### 1. Chosen Shard Key
Shard key: MemberID

### Why MemberID satisfies the required criteria
1. High cardinality
- MemberID is an auto-increment primary key, so it grows with users and is naturally high-cardinality.

2. Query-aligned
- Many core API routes are member-centric, for example portfolio, follow/follower relations, and member post listing.
- This means routing by MemberID aligns with frequent lookup and write paths.

3. Stable
- MemberID does not change after insertion, so records do not need re-sharding because of key updates.

### 2. Partitioning Strategy
Chosen strategy: Hash-based sharding

Routing function (for 3 shards):

shard_id = MemberID % 3

### Why hash-based is suitable here
- Better balance than range sharding for growing auto-increment IDs.
- Simple deterministic routing in application code.
- Works well for single-key lookups and inserts when MemberID is known.

### 3. Estimated Distribution and Skew Risk

#### Current sample estimate (from seed data)
- Members: IDs 1..20 produce near-even distribution across 3 shards
  - Shard 0: 6 members
  - Shard 1: 7 members
  - Shard 2: 7 members

- Posts (using post owner MemberID from sample data):
  - Shard 0: 4 posts
  - Shard 1: 9 posts
  - Shard 2: 7 posts

The post distribution is acceptable for a small sample, but it already shows activity skew.

#### Skew risks to note
- Power users can create many posts/comments and overload one shard.
- Social graph hotspots (many followers of one member) can create uneven load patterns.
- Global feed/search endpoints may require fan-out queries across shards.

### 4. Note on Candidate Keys Not Chosen
- Department is available but low-cardinality and likely skewed.
- Range-based MemberID sharding could create hot future shards as IDs increase.

Hence, hash(MemberID) is the most practical and defensible choice for this codebase.

## Sub-task 2: Implement Data Partitioning

## Sub-task 3: Implement Query Routing

## Sub-task 4: Scalability and Trade-offs Analysis

