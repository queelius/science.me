# hub-baseline

This is the persistence baseline used by forecast hubs: the best guess for the coming weeks is the most recent week, here the lens's nowcast of it, scaled to what the resolution vintage will report. It assumes no mechanism at all, which is why it is useful: a theory that cannot beat "next week looks like last week" has not shown that its mechanism predicts anything.

Its uncertainty comes from the data alone. Log counts are treated as a random walk without drift, so the spread of the last 8 weekly changes sets the variance of one step, and a target several weeks out has proportionally more. That variance is matched by a negative binomial around the persistence mean.
