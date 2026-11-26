# Stop assignment

Each time routes are built, the app works through the day's stops in two passes.

## Pass 1: volunteers

1. Each working volunteer is given **their own usual stops** that are on today's list.
2. Any room left within their limits is filled with **extra stops** from the rest of the list, taken from their assigned zip codes if they have any. These are labeled *Added today* and are for today only.

The aim in this pass is first to place as many stops with volunteers as their limits allow, and then to do so with the least driving time or miles.

## Pass 2: staff

Everything left is shared among the staff drivers working today, along with any volunteer who has no limits at all.

How it is shared is a [setting](settings.md#planning):

| Setting | Result |
|---|---|
| **Roughly the same number of stops each** (the default) | No driver takes more than about 20% above an even share. |
| **Roughly the same driving time each** | Drivers end up with similar driving times. |
| **No sharing: lowest total only** | Only the day's total is minimized. One driver usually ends up with nearly everything. |

## Route order

Each driver's stops are then put in the order that gives the least driving time or miles, starting at the driver's start location and finishing at their end location. A route you have [arranged by hand](../daily/adjust.md#reordering-a-route) keeps your order.

## Special cases

**A volunteer is off today.** Their usual stops on today's list go to other drivers for the day and are labeled *Covering for* and their name. The stops remain theirs.

**A volunteer's usual stops do not fit their limits.** The ones that do not fit go to other drivers for the day and are labeled *Over* their name *'s limit*. For a locked volunteer nothing is moved; their route is flagged as over the limit instead.

**You moved a stop.** A stop you moved goes to the driver you chose, for today. If that takes a volunteer over a limit, the move stands and the route is flagged. The one exception is a [locked](drivers.md#lock) volunteer: a move made before the lock was turned on is not followed while the lock is on.

**No staff driver is working.** Stops the volunteers cannot take are listed as not on any route, each with the reason.

**A driver avoids highways.** Their travel times are worked out along roads that avoid highways where there is a reasonable alternative. When the day is optimized for least miles, such a driver's stop order is chosen for least miles, while each leg between stops follows the fastest road that avoids highways.

**Two orders cost exactly the same.** A loop driven clockwise or anticlockwise takes the same time. When that happens the app may give either direction, and a rebuild may give the other.

## Factors that do not affect assignment

- **Estimated arrival times** and the minutes allowed at each stop. They are worked out after the stops are handed out.
- **Notes.**
- **The order of the pasted list.**
