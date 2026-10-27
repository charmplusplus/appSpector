# pfield: appSpector's demonstration program. Point CHARM_HOME at a Charm++
# build with liveViz (TARGET=LIBS), the CommonLBs module and tracing
# (--enable-tracing: -tracemode utilization gives the viewer its over-time pane).
UNAME := $(shell uname -s)-$(shell uname -m)
ifeq ($(UNAME),Darwin-arm64)
  ARCH ?= reconverse-darwin-arm8
else ifeq ($(UNAME),Linux-x86_64)
  ARCH ?= reconverse-linux-x86_64
else
  ARCH ?= reconverse-linux-arm8
endif
REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
CHARM_HOME ?= $(REPO)/charm-wt/$(ARCH)
CHARMC = $(CHARM_HOME)/bin/charmc $(OPTS)
# libmoduleliveViz.dep asks for -ljpeg; MacPorts keeps it in /opt/local/lib
EXTRA_LDFLAGS ?= $(shell [ -d /opt/local/lib ] && echo -L/opt/local/lib)

all: pfield

pfield: pfield.o
	$(CHARMC) -language charm++ -module liveViz -module CommonLBs -tracemode utilization -balancer GreedyRefineLB $(EXTRA_LDFLAGS) -o $@ pfield.o

pfield.o: pfield.C pfield.decl.h pfield.def.h
	$(CHARMC) -O2 -c pfield.C

pfield.decl.h pfield.def.h: pfield.ci
	$(CHARMC) pfield.ci

clean:
	rm -f pfield pfield.o pfield.decl.h pfield.def.h charmrun *.log
