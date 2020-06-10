/*
 *
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 *
 */

#include <proton/condition.h>
#include <proton/raw_connection.h>
#include <proton/listener.h>
#include <proton/netaddr.h>
#include <proton/proactor.h>

#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct app_data_t {
  const char *host, *port;
  const char *amqp_address;

  pn_proactor_t *proactor;
  pn_listener_t *listener;

  int64_t first_idle_time;
  int64_t try_accept_time;
  int64_t wake_conn_time;
  int connects;
  int disconnects;

  /* Sender values */

  /* Receiver values */
} app_data_t;

#define MAX_CONNECTIONS 5

typedef struct conn_data_t {
  pn_raw_connection_t *connection;
  int64_t last_recv_time;
  int bytes;
  int buffers;
} conn_data_t;

static conn_data_t conn_data[MAX_CONNECTIONS] = {{0}};

static int exit_code = 0;

/* Close the connection and the listener so so we will get a
 * PN_PROACTOR_INACTIVE event and exit, once all outstanding events
 * are processed.
 */
static void close_all(pn_raw_connection_t *c, app_data_t *app) {
  if (c) pn_raw_connection_close(c);
  if (app->listener) pn_listener_close(app->listener);
}

static bool check_condition(pn_event_t *e, pn_condition_t *cond, app_data_t *app) {
  if (pn_condition_is_set(cond)) {
    fprintf(stderr, "%s: %s: %s\n", pn_event_type_name(pn_event_type(e)),
            pn_condition_get_name(cond), pn_condition_get_description(cond));
    return true;
  }

  return false;
}

static void check_condition_fatal(pn_event_t *e, pn_condition_t *cond, app_data_t *app) {
  if (check_condition(e, cond, app)) {
    close_all(pn_event_raw_connection(e), app);
    exit_code = 1;
  }
}

static void recv_message(pn_raw_buffer_t buf) {
  fwrite(buf.bytes, buf.size, 1, stdout);
}

conn_data_t *make_conn_data(pn_raw_connection_t *c) {
  int i;
  for (i = 0; i < MAX_CONNECTIONS; ++i) {
    if (!conn_data[i].connection) {
      conn_data[i].connection = c;
      return &conn_data[i];
    }
  }
  return NULL;
}

void free_conn_data(conn_data_t *c) {
  if (!c) return;
  c->connection = NULL;
}

#define READ_BUFFERS 4

/* This function handles events when we are acting as the receiver */
static void handle_receive(app_data_t *app, pn_event_t* event) {
  switch (pn_event_type(event)) {

    case PN_RAW_CONNECTION_CONNECTED: {
      pn_raw_connection_t *c = pn_event_raw_connection(event);
      conn_data_t *cd = (conn_data_t *) pn_raw_connection_get_context(c);
      pn_raw_buffer_t buffers[READ_BUFFERS] = {{0}};
      if (cd) {
        int i = READ_BUFFERS;
        printf("**raw connection %ld connected\n", cd-conn_data);
        app->connects++;
        for (; i; --i) {
          pn_raw_buffer_t *buff = &buffers[READ_BUFFERS-i];
          buff->bytes = (char*) malloc(1024);
          buff->capacity = 1024;
          buff->size = 0;
          buff->offset = 0;
        }
        pn_raw_connection_give_read_buffers(c, buffers, READ_BUFFERS);
      } else {
        printf("**raw connection connected: not connected\n");
      }
    } break;

    case PN_RAW_CONNECTION_WAKE: {
      pn_raw_connection_t *c = pn_event_raw_connection(event);
      conn_data_t *cd = (conn_data_t *) pn_raw_connection_get_context(c);
      printf("**raw connection %ld woken\n", cd-conn_data);
    } break;

    case PN_RAW_CONNECTION_DISCONNECTED: {
      pn_raw_connection_t *c = pn_event_raw_connection(event);
      conn_data_t *cd = (conn_data_t *) pn_raw_connection_get_context(c);
      if (cd) {
        printf("**raw connection %ld disconnected: bytes: %d, buffers: %d\n", cd-conn_data, cd->bytes, cd->buffers);
      } else {
        printf("**raw connection disconnected: not connected\n");
      }
      app->disconnects++;
      check_condition(event, pn_raw_connection_condition(c), app);
      free_conn_data(cd);
    } break;

    case PN_RAW_CONNECTION_NEED_READ_BUFFERS: {
    } break;

    /* This path handles both received bytes and freeing buffers at close */
    case PN_RAW_CONNECTION_READ: {
      pn_raw_connection_t *c = pn_event_raw_connection(event);
      conn_data_t *cd = (conn_data_t *) pn_raw_connection_get_context(c);
      pn_raw_buffer_t buffs[READ_BUFFERS];
      size_t n;
      cd->last_recv_time = pn_proactor_now_64();
      while ( (n = pn_raw_connection_take_read_buffers(c, buffs, READ_BUFFERS)) ) {
        unsigned i;
        for (i=0; i<n && buffs[i].bytes; ++i) {
          cd->bytes += buffs[i].size;
          recv_message(buffs[i]);
        }
        cd->buffers += n;

        if (!pn_raw_connection_is_write_closed(c)) {
          pn_raw_connection_write_buffers(c, buffs, n);
        } else if (!pn_raw_connection_is_read_closed(c)) {
          pn_raw_connection_give_read_buffers(c, buffs, n);
        } else {
          unsigned i;
          for (i=0; i<n && buffs[i].bytes; ++i) {
            free(buffs[i].bytes);
          }
        }
      }
    } break;
    case PN_RAW_CONNECTION_CLOSED_WRITE:
    case PN_RAW_CONNECTION_CLOSED_READ: {
      pn_raw_connection_t *c = pn_event_raw_connection(event);
      pn_raw_connection_close(c);
    } break;
    case PN_RAW_CONNECTION_WRITTEN: {
      pn_raw_connection_t *c = pn_event_raw_connection(event);
      pn_raw_buffer_t buffs[READ_BUFFERS];
      size_t n;
      while ( (n = pn_raw_connection_take_written_buffers(c, buffs, READ_BUFFERS)) ) {
        if (!pn_raw_connection_is_read_closed(c)) {
          pn_raw_connection_give_read_buffers(c, buffs, n);
        } else {
          unsigned i;
          for (i=0; i<n && buffs[i].bytes; ++i) {
            free(buffs[i].bytes);
          }
        }
      };
    } break;
    default:
      break;
  }
}

#define WRITE_BUFFERS 4

/* Handle all events, delegate to handle_send or handle_receive
   Return true to continue, false to exit
*/
static bool handle(app_data_t* app, pn_event_t* event) {
  switch (pn_event_type(event)) {

    case PN_LISTENER_OPEN: {
      char port[256];             /* Get the listening port */
      pn_netaddr_host_port(pn_listener_addr(pn_event_listener(event)), NULL, 0, port, sizeof(port));
      printf("**listening on %s\n", port);
      fflush(stdout);
      break;
    }
    case PN_LISTENER_ACCEPT: {
      pn_listener_t *listener = pn_event_listener(event);
      pn_raw_connection_t *c = pn_raw_connection();
      void *cd = make_conn_data(c);
      int64_t now = pn_proactor_now_64();

      if (cd) {
        app->first_idle_time = 0;
        app->try_accept_time = 0;
        if (app->wake_conn_time < now) {
          app->wake_conn_time = now + 5000;
          pn_proactor_set_timeout(pn_listener_proactor(listener), 5000);
        }
        pn_raw_connection_set_context(c, cd);

        pn_listener_raw_accept(listener, c);
      } else {
        printf("**too many connections, trying again later...\n");

        /* No other way to reject connection */
        pn_listener_raw_accept(listener, c);
        pn_raw_connection_close(c);
      }

    } break;

    case PN_LISTENER_CLOSE: {
      app->listener = NULL;        /* Listener is closed */
      check_condition_fatal(event, pn_listener_condition(pn_event_listener(event)), app);
    } break;

    case PN_PROACTOR_TIMEOUT: {
      int64_t now = pn_proactor_now_64();
      pn_millis_t timeout = 5000;
      if (app->connects - app->disconnects == 0) {
        timeout = 20000;
        if (app->first_idle_time == 0) {
          printf("**idle detected, shutting down in %dms\n", timeout);
          app->first_idle_time = now;
        } else if (app->first_idle_time + 20000 <= now) {
          pn_listener_close(app->listener);
          break;
        }
      } else if (now >= app->wake_conn_time) {
        int i;
        for (i = 0; i < MAX_CONNECTIONS; ++i) {
          if (conn_data[i].connection) pn_raw_connection_wake(conn_data[i].connection);
        }
        app->wake_conn_time = now + 5000;
      }
      pn_proactor_set_timeout(pn_event_proactor(event), timeout);
    }  break;

    case PN_PROACTOR_INACTIVE: {
      return false;
    } break;

    default: {
      pn_raw_connection_t *c = pn_event_raw_connection(event);
      if (c) {
          handle_receive(app, event);
      }
    }
  }
  return exit_code == 0;
}

void run(app_data_t *app) {
  /* Loop and handle events */
  do {
    pn_event_batch_t *events = pn_proactor_wait(app->proactor);
    pn_event_t *e;
    for (e = pn_event_batch_next(events); e; e = pn_event_batch_next(events)) {
      if (!handle(app, e)) {
        return;
      }
    }
    pn_proactor_done(app->proactor, events);
  } while(true);
}

int main(int argc, char **argv) {
  struct app_data_t app = {0};
  char addr[PN_MAX_ADDR];
  app.host = (argc > 1) ? argv[1] : "";
  app.port = (argc > 2) ? argv[2] : "amqp";

  /* Create the proactor and connect */
  app.proactor = pn_proactor();
  app.listener = pn_listener();
  pn_proactor_addr(addr, sizeof(addr), app.host, app.port);
  pn_proactor_listen(app.proactor, app.listener, addr, 16);
  run(&app);
  pn_proactor_free(app.proactor);
  return exit_code;
}
