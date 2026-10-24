/* pfield: particles in cells under a forcing field, a demonstration
   program for appSpector (live liveViz image + live per-chare load).

   A K x K chare array of cells covers the box. Every cell owns a vector
   of particles that move inside the cell, either by a random walk or
   under a time-varying forcing field sampled on a small local mesh
   (bilinear interpolation, a proxy for the particle-mesh step of a PIC
   or PPPM code). A move that would leave the cell is dropped, so no
   particle ever changes chare: the cost of a chare is its particle
   count times the per-particle work, and the whole job is load-bound
   with no neighbour communication at all.

   Load drifts on its own: particles die at a small rate per step and are
   born at a rate that follows a hot spot circling the box. Load can also
   be created by hand: the CCS handler "pfieldInject" drops a Gaussian
   blob of particles at a point (the viewer sends one per mouse click),
   and "pfieldBalance" runs one load-balancing step at the next
   iteration (the Balance button). The run is lock-step: every step ends
   in a reduction to Main, so an overloaded PE shows as idle time on all
   the others, which is what the per-PE load bars display.

   Arguments: -k cells per side (8) -n initial particles per cell (300)
   -mode walk|field (field) -w extra field terms per particle (16)
   -death per-particle death rate per second of wall time (0.02: a
          particle lives about 50 s) -birth birth rate per second relative
          to -n (same as -death, so the count sits near -n times the hot spot)
   -hot hot-spot amplitude (3.0) -period seconds per hot-spot orbit (120)
   -lb automatic AtSync period in steps (0 = only on request)
   -steps number of steps (0 = until killed) -box box size (100)
   Run with ++server ++server-port N for the viewer. */

#include <algorithm>
#include <cmath>
#include <random>
#include <vector>

#include "liveViz.h"
#include "pup_toNetwork.h"
#include "pfield.decl.h"

/* readonly */ CProxy_Main mainProxy;
/* readonly */ CProxy_Cell cells;
/* readonly */ int K;
/* readonly */ double boxSize;
/* readonly */ int moveMode;
/* readonly */ int workTerms;
/* readonly */ double deathRate;
/* readonly */ double birthRate;
/* readonly */ int baseCount;
/* readonly */ double hotAmp;
/* readonly */ double hotPeriod;

static const int MESH = 8;          // local mesh points per side (MESH+1 nodes)

struct Particle {
  double x, y, vx, vy;
  void pup(PUP::er &p) { p | x; p | y; p | vx; p | vy; }
};

/* Where births concentrate: a Gaussian bump whose centre circles the box
   once per hotPeriod seconds. Shared by the cells (birth rate) and the
   image (background shading). */
static void hotSpotCentre(double t, double &cx, double &cy) {
  double a = 2 * M_PI * t / hotPeriod;
  cx = boxSize * (0.5 + 0.3 * cos(a));
  cy = boxSize * (0.5 + 0.3 * sin(a));
}
static double hotSpot(double x, double y, double t) {
  double cx, cy;
  hotSpotCentre(t, cx, cy);
  double s = 0.15 * boxSize;
  double d2 = (x - cx) * (x - cx) + (y - cy) * (y - cy);
  return 1.0 + hotAmp * exp(-d2 / (2 * s * s));
}

/* The forcing field: a swirl around a slowly moving centre plus a weak
   pull toward it. Evaluated on each cell's local mesh once per step. */
static void forcing(double x, double y, double t, double &fx, double &fy) {
  double cx, cy;
  hotSpotCentre(t * 0.5, cx, cy);
  double dx = x - cx, dy = y - cy;
  double r2 = dx * dx + dy * dy;
  double swirl = 6.0 / (r2 + 100.0);      // units/s^2 per unit of distance; gentle circulation
  fx = -dy * swirl - 0.004 * dx;
  fy = dx * swirl - 0.004 * dy;
}

class Main : public CBase_Main {
  int stepNo, steps, lbPeriod;
  bool lbRequested, inLB;
  double t0, lastPrint;
public:
  Main(CkArgMsg *m) {
    K = 8; baseCount = 300; moveMode = 1; workTerms = 16;
    deathRate = 0.02; birthRate = -1; hotAmp = 3.0; hotPeriod = 120.0;
    lbPeriod = 0; steps = 0; boxSize = 100.0;
    for (int i = 1; i + 1 < m->argc; i++) {
      std::string a = m->argv[i];
      const char *v = m->argv[i + 1];
      if (a == "-k") K = atoi(v);
      else if (a == "-n") baseCount = atoi(v);
      else if (a == "-mode") moveMode = (std::string(v) == "walk") ? 0 : 1;
      else if (a == "-w") workTerms = atoi(v);
      else if (a == "-death") deathRate = atof(v);
      else if (a == "-birth") birthRate = atof(v);
      else if (a == "-hot") hotAmp = atof(v);
      else if (a == "-period") hotPeriod = atof(v);
      else if (a == "-lb") lbPeriod = atoi(v);
      else if (a == "-steps") steps = atoi(v);
      else if (a == "-box") boxSize = atof(v);
      else continue;
      i++;
    }
    delete m;
    if (birthRate < 0) birthRate = deathRate;
    mainProxy = thisProxy;
    stepNo = 0; lbRequested = false; inLB = false;
    t0 = CkWallTimer(); lastPrint = t0;

    CkPrintf("pfield: %dx%d cells, %d particles per cell, mode %s, %d field terms, "
             "death %.3f birth %.3f per second, hot spot x%.1f every %.0f s, LB period %d, %d PEs\n",
             K, K, baseCount, moveMode ? "field" : "walk", workTerms, deathRate, birthRate,
             hotAmp, hotPeriod, lbPeriod, CkNumPes());

    CkArrayOptions opts(K, K);
    cells = CProxy_Cell::ckNew(opts);
    liveVizConfig cfg(liveVizConfig::pix_color, true);
    liveVizInit(cfg, cells, CkCallback(CkIndex_Cell::requestNextFrame(0), cells), opts);

    CcsRegisterHandler("pfieldInject", CkCallback(CkIndex_Main::ccsInject(NULL), thisProxy));
    CcsRegisterHandler("pfieldBalance", CkCallback(CkIndex_Main::ccsBalance(NULL), thisProxy));
    CkPrintf("pfield: CCS handlers pfieldInject (x y sigma count, network order) and pfieldBalance\n");

    cells.step(stepNo);
  }

  void stepDone(int total) {
    stepNo++;
    double now = CkWallTimer();
    if (now - lastPrint >= 5.0) {
      CkPrintf("pfield: step %d, %d particles, %.1f steps/s\n", stepNo, total,
               stepNo / (now - t0));
      lastPrint = now;
    }
    if (steps > 0 && stepNo >= steps) {
      CkPrintf("pfield: done after %d steps\n", stepNo);
      CkExit();
      return;
    }
    if (lbRequested || (lbPeriod > 0 && stepNo % lbPeriod == 0)) {
      lbRequested = false;
      inLB = true;
      CkPrintf("pfield: load balancing at step %d\n", stepNo);
      cells.doBalance();
      return;
    }
    cells.step(stepNo);
  }

  void lbDone() {
    inLB = false;
    CkPrintf("pfield: load balancing done, resuming at step %d\n", stepNo);
    cells.step(stepNo);
  }

  /* "pfieldInject": request data is x, y, sigma as fractions of the box
     (network-order doubles) and an int32 count. Samples the blob here and
     hands each cell the particles that fall inside it. */
  void ccsInject(CkCcsRequestMsg *m) {
    double fx = 0.5, fy = 0.5, fs = 0.05;
    int count = 500;
    if (m->length >= 28) {
      PUP_toNetwork_unpack p(m->data);
      p | fx; p | fy; p | fs; p | count;
    }
    count = std::max(0, std::min(count, 200000));
    std::mt19937 rng((unsigned)(CkWallTimer() * 1e6));
    std::normal_distribution<double> gx(fx * boxSize, fs * boxSize), gy(fy * boxSize, fs * boxSize);
    double cellSize = boxSize / K;
    std::vector<std::vector<double>> xs(K * K), ys(K * K);
    for (int i = 0; i < count; i++) {
      double x = gx(rng), y = gy(rng);
      if (x < 0 || x >= boxSize || y < 0 || y >= boxSize) continue;
      int ci = (int)(x / cellSize), cj = (int)(y / cellSize);
      xs[ci * K + cj].push_back(x);
      ys[ci * K + cj].push_back(y);
    }
    int touched = 0;
    for (int ci = 0; ci < K; ci++)
      for (int cj = 0; cj < K; cj++)
        if (!xs[ci * K + cj].empty()) {
          cells(ci, cj).inject(xs[ci * K + cj], ys[ci * K + cj]);
          touched++;
        }
    CkPrintf("pfield: injected %d particles around (%.2f, %.2f) sigma %.3f into %d cells\n",
             count, fx, fy, fs, touched);
    char reply[64];
    int n = snprintf(reply, sizeof reply, "injected %d into %d cells", count, touched);
    CcsSendDelayedReply(m->reply, n + 1, reply);
    delete m;
  }

  /* "pfieldBalance": one load-balancing step at the end of the current iteration. */
  void ccsBalance(CkCcsRequestMsg *m) {
    const char *reply = inLB ? "already balancing" : "balancing at the next step";
    if (!inLB) lbRequested = true;
    CcsSendDelayedReply(m->reply, strlen(reply) + 1, reply);
    delete m;
  }
};

class Cell : public CBase_Cell {
  std::vector<Particle> particles;
  double x0, y0, cellSize;     // my box: [x0, x0+cellSize) x [y0, y0+cellSize)
  std::mt19937 rng;
  double meshFx[MESH + 1][MESH + 1], meshFy[MESH + 1][MESH + 1];
  double births;               // fractional births carried between steps
  double lastStepTime;         // wall clock of the previous step (rates are per second)

  void seed() { rng.seed(1234567u + 1000003u * thisIndex.x + 7919u * thisIndex.y + (unsigned)particles.size()); }

  void sampleMesh(double t) {
    for (int i = 0; i <= MESH; i++)
      for (int j = 0; j <= MESH; j++)
        forcing(x0 + i * cellSize / MESH, y0 + j * cellSize / MESH, t, meshFx[i][j], meshFy[i][j]);
  }

  void meshForce(double x, double y, double &fx, double &fy) const {
    double u = (x - x0) / cellSize * MESH, v = (y - y0) / cellSize * MESH;
    int i = std::min(MESH - 1, std::max(0, (int)u)), j = std::min(MESH - 1, std::max(0, (int)v));
    double a = u - i, b = v - j;
    fx = (1 - a) * (1 - b) * meshFx[i][j] + a * (1 - b) * meshFx[i + 1][j]
       + (1 - a) * b * meshFx[i][j + 1] + a * b * meshFx[i + 1][j + 1];
    fy = (1 - a) * (1 - b) * meshFy[i][j] + a * (1 - b) * meshFy[i + 1][j]
       + (1 - a) * b * meshFy[i][j + 1] + a * b * meshFy[i + 1][j + 1];
    // a vortex around the cell centre keeps the particles circulating inside
    // the cell instead of collecting on the wall the large-scale field pushes toward
    double xc = x0 + cellSize / 2, yc = y0 + cellSize / 2, omega = 0.15;
    fx += -(y - yc) * omega;
    fy += (x - xc) * omega;
    // extra per-particle work: a short series correction, workTerms long
    double s = 0.0, arg = 0.3 * (x + y);
    for (int k = 1; k <= workTerms; k++) s += sin(k * arg) / (k * k);
    fx += 1e-3 * s;
    fy -= 1e-3 * s;
  }

public:
  Cell() {
    usesAtSync = true;
    cellSize = boxSize / K;
    x0 = thisIndex.x * cellSize;
    y0 = thisIndex.y * cellSize;
    births = 0.0;
    lastStepTime = CkWallTimer();
    seed();
    std::uniform_real_distribution<double> ux(x0, x0 + cellSize), uy(y0, y0 + cellSize);
    particles.resize(baseCount);
    for (Particle &p : particles) { p.x = ux(rng); p.y = uy(rng); p.vx = p.vy = 0.0; }
  }
  Cell(CkMigrateMessage *m) : CBase_Cell(m) {}

  void pup(PUP::er &p) {
    p | particles; p | x0; p | y0; p | cellSize; p | births;
    if (p.isUnpacking()) { seed(); lastStepTime = CkWallTimer(); }
  }

  void step(int stepNo) {
    double t = CkWallTimer();
    double dtWall = std::min(1.0, std::max(0.0, t - lastStepTime));   // seconds since the last step
    lastStepTime = t;
    // Motion is in wall-clock time, so it looks the same at any step rate:
    // a particle crosses a cell in a few seconds whether the machine does
    // 100 or 10000 steps per second.
    const double damp = exp(-0.5 * dtWall);                 // velocity e-folds in 2 s
    const double walk = 0.3 * cellSize * sqrt(dtWall);      // random walk, ~0.3 cell per sqrt(s)
    const double jitter = 0.2 * cellSize * sqrt(dtWall);    // thermal motion added to the field mode
    std::uniform_real_distribution<double> uw(-walk, walk), uj(-jitter, jitter);
    if (moveMode == 1) sampleMesh(t);
    for (Particle &p : particles) {
      double nx, ny;
      if (moveMode == 1) {
        double fx, fy;
        meshForce(p.x, p.y, fx, fy);
        p.vx = damp * p.vx + fx * dtWall;
        p.vy = damp * p.vy + fy * dtWall;
        nx = p.x + p.vx * dtWall + uj(rng);
        ny = p.y + p.vy * dtWall + uj(rng);
      } else {
        nx = p.x + uw(rng);
        ny = p.y + uw(rng);
      }
      // a move that would leave the cell is recalculated as a bounce off
      // the cell wall: particles never change chare
      if (nx < x0 || nx >= x0 + cellSize) { p.vx = -p.vx; nx = p.x; }
      if (ny < y0 || ny >= y0 + cellSize) { p.vy = -p.vy; ny = p.y; }
      p.x = nx; p.y = ny;
    }
    // deaths: binomial thinning
    if (deathRate > 0 && !particles.empty()) {
      std::binomial_distribution<int> bd((int)particles.size(), std::min(1.0, deathRate * dtWall));
      int dead = bd(rng);
      for (int i = 0; i < dead && !particles.empty(); i++) {
        std::uniform_int_distribution<size_t> pick(0, particles.size() - 1);
        size_t k = pick(rng);
        particles[k] = particles.back();
        particles.pop_back();
      }
    }
    // births: rate follows the hot spot over my cell centre
    births += birthRate * baseCount * hotSpot(x0 + cellSize / 2, y0 + cellSize / 2, t) * dtWall;
    if (births >= 1.0) {
      std::poisson_distribution<int> pd(births);
      int born = pd(rng);
      births = 0.0;
      std::uniform_real_distribution<double> ux(x0, x0 + cellSize), uy(y0, y0 + cellSize);
      for (int i = 0; i < born; i++) particles.push_back(Particle{ux(rng), uy(rng), 0.0, 0.0});
    }
    int n = (int)particles.size();
    contribute(sizeof(int), &n, CkReduction::sum_int, CkCallback(CkReductionTarget(Main, stepDone), mainProxy));
  }

  void inject(const std::vector<double> &xs, const std::vector<double> &ys) {
    for (size_t i = 0; i < xs.size(); i++) particles.push_back(Particle{xs[i], ys[i], 0.0, 0.0});
  }

  void doBalance() { AtSync(); }
  void ResumeFromSync() {
    contribute(CkCallback(CkReductionTarget(Main, lbDone), mainProxy));
  }

  /* The image: my rectangle of the requested picture. Background shade is
     the birth hot spot (where load will grow), particles are bright dots,
     cell borders dark grey. */
  void requestNextFrame(liveVizRequestMsg *m) {
    int wid = m->req.wid, ht = m->req.ht;
    int myW = std::max(1, wid / K), myH = std::max(1, ht / K);
    int sx = thisIndex.x * myW, sy = thisIndex.y * myH;
    if (thisIndex.x == K - 1) myW = wid - sx;     // last column/row take the remainder
    if (thisIndex.y == K - 1) myH = ht - sy;
    std::vector<unsigned char> img(3 * myW * myH);
    double t = CkWallTimer();
    for (int j = 0; j < myH; j++)
      for (int i = 0; i < myW; i++) {
        double x = x0 + (i + 0.5) * cellSize / myW, y = y0 + (j + 0.5) * cellSize / myH;
        double h = (hotSpot(x, y, t) - 1.0) / std::max(hotAmp, 1e-9);   // 0..1
        unsigned char *px = &img[3 * (j * myW + i)];
        px[0] = (unsigned char)(20 + 120 * h);
        px[1] = (unsigned char)(20 + 30 * h);
        px[2] = (unsigned char)(60 + 40 * (1 - h));
        if (i == 0 || j == 0) { px[0] = px[1] = px[2] = 70; }
      }
    for (const Particle &p : particles) {
      int i = (int)((p.x - x0) / cellSize * myW), j = (int)((p.y - y0) / cellSize * myH);
      if (i < 0 || i >= myW || j < 0 || j >= myH) continue;
      unsigned char *px = &img[3 * (j * myW + i)];
      px[0] = 255; px[1] = 235; px[2] = 120;
    }
    liveVizDeposit(m, sx, sy, myW, myH, img.data(), this);
  }
};

#include "pfield.def.h"
