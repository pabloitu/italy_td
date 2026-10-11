# Which days had a broken inlabru_td MAP? Repeats only the BFGS step of ETAS.map, exactly as the model ran it
# (same input selection, fit window, start values, settings), and classifies the result:
#   ok       BFGS ended inside the physical box: forecast made with a regular MAP
#   error    BFGS stopped with an error: the old code crashed, the fixed code uses the bounded search
#   outside  BFGS "converged" outside the box (spurious maximum): forecast, if it exists, is invalid
# Runs inside the inlabru_td image (cwd /app, model source in /app/source).
# usage: Rscript inlabru_map_audit.R CATALOG START NDAYS [CORES] [MAG_COMPL=2.5] [FIT_YEARS=1]
a <- commandArgs(TRUE)
suppressMessages({source('source/source_inlabru_utilities.R'); library(parallel)})
cat.file <- a[1]; start <- as.Date(a[2]); nd <- as.integer(a[3])
cores <- if(length(a) > 3) as.integer(a[4]) else detectCores()
m0 <- if(length(a) > 4) as.numeric(a[5]) else 2.5; fy <- if(length(a) > 5) as.numeric(a[6]) else 1

# same selection as source_inlabru_1dayfore.R on the floatCSEP input catalog
ct <- read.csv(cat.file); ct$M <- ct$mag
cxy <- read.table('data/collection.area.dat')
ct <- ct[!is.na(ct$depth) & ct$depth <= 30 & sp::point.in.polygon(ct$lon, ct$lat, cxy[,1], cxy[,2]) > 0, ]
ct$td <- as.POSIXct(gsub('T', ' ', ct$time_string), tz = 'UTC')
ct <- ct[ct$M >= m0, ]; ct <- ct[order(ct$td), ]
lo <- c(-20, -15, -5, -15, -10, -20); hi <- c(10, 10, 2, 5, 5, 5)
init <- c(-0.3734126, 0.5474037, -0.2237425, -2.0321369, 0.1422050, -5.3822198)
pm <- c(0,0,0,0,0,-3); pp <- c(5,3,3,3,3,15)

one <- function(k){
  s <- as.POSIXct(paste(start + k, '00:00:00'), tz = 'UTC')
  c0 <- ct[ct$td < s, ]
  d5 <- c0[c0$td >= s - fy*365.25*86400, ]
  xl <- range(c0$lon) + c(-0.01, 0.01); yl <- range(c0$lat) + c(-0.01, 0.01)
  bdy <- as(sp::SpatialPolygons(list(sp::Polygons(list(sp::Polygon(cbind(xl[c(1,2,2,1,1)], yl[c(1,1,2,2,1)]))), 'A'))),
            'SpatialPolygonsDataFrame')
  df <- data.frame(x = d5$lon, y = d5$lat, ts = as.numeric(difftime(d5$td, min(d5$td), units = 'days')), mags = d5$M)[-1, ]
  lp <- ETAS.lpost(df, m0, 0, max(df$ts) + 0.001, bdy, pm, pp)
  t0 <- Sys.time()
  o <- try(optim(init, lp, method = 'BFGS', control = list(fnscale = -1, maxit = 500, reltol = 1e-10)), silent = TRUE)
  st <- if(inherits(o, 'try-error')) 'error' else if(any(o$par < lo | o$par > hi)) 'outside' else 'ok'
  th <- if(st == 'error') rep(NA, 6) else o$par
  sprintf('%s %5d %-7s %6.0f %10.1f  %s', format(start + k), nrow(df), st, as.numeric(Sys.time() - t0, units = 'secs'),
          if(st == 'error') NA else o$value, paste(sprintf('%7.2f', th), collapse = ' '))
}
# longest days first so the cores stay busy
ord <- order(-sapply(0:(nd - 1), function(k) sum(ct$td < as.POSIXct(paste(start + k, '00:00:00'), tz = 'UTC') &
                                                 ct$td >= as.POSIXct(paste(start + k, '00:00:00'), tz = 'UTC') - fy*365.25*86400))) - 1
res <- unlist(mclapply(ord, one, mc.cores = cores, mc.preschedule = FALSE))
res <- sort(res)
cat('date        events status   secs  log-post   th1..th6 (BFGS result)\n')
cat(res, sep = '\n')
st <- sub('^\\S+\\s+\\d+\\s+(\\S+).*', '\\1', res)
cat(sprintf('\n%d days: %d ok, %d error, %d outside\n', length(res), sum(st == 'ok'), sum(st == 'error'), sum(st == 'outside')))
cat('to recompute (error or outside):', sub(' .*', '', res[st != 'ok']), '\n')
