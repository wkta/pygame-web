import math
import random
import katagames_sdk.engine as kataen


BaseGame = kataen.BaseGame
pygame = kataen.pygame
EventReceiver = kataen.EventReceiver
EngineEvTypes = kataen.EngineEvTypes
Vector2 = pygame.Vector2


############## art.py ##############

class Art:
    ENEMIES = [None] * 4
    PICKUPS = [None] * 5

    @staticmethod
    def subsurface(surf, rect, colorkey=(0xFF, 0x00, 0xFF)):  # XXX Surface.subsurface not supported in web mode~
        res = pygame.Surface((rect[2], rect[3]))
        res.blit(surf, (0, 0), rect)
        res.set_colorkey(colorkey)
        return res

    @staticmethod
    def load_from_disk():
        full_sheet = pygame.image.load("assets/art.png").convert_alpha()
        for i in range(4):
            Art.ENEMIES[i] = Art.subsurface(full_sheet, [i * 16, 0, 16, 32])
        for i in range(5):
            Art.PICKUPS[i] = Art.subsurface(full_sheet, [i * 16, 32, 16, 32])

############## art.py ##############

############## raycaster.py ##############

class RayEmitter:

    def __init__(self, xy, direction, fov, n_rays, max_depth=100):
        self.xy = xy
        self.direction = direction
        self.fov = fov
        self.n_rays = max(n_rays, 3)
        self.max_depth = max_depth

    def get_rays(self):
        left_ray = self.direction.rotate(-self.fov[0] / 2)
        for i in range(self.n_rays):
            yield left_ray.rotate((i + 0.5) * self.fov[0] / self.n_rays)


class Player(RayEmitter):

    def __init__(self, xy, fov=(60, 45), n_rays=50, move_speed=40, turn_speed=160, sight=200):
        super().__init__(xy, Vector2(0, 1).rotate(random.random() * 360), fov, n_rays, max_depth=sight)
        self.move_speed = move_speed  # units per second
        self.turn_speed = turn_speed
        self.z = 0
        self._z_vel = 0
        self.grav = -15

    def move(self, forward, strafe, dt, state: 'GameState' = None):
        new_xy = Vector2(self.xy)
        if forward != 0:
            new_xy += self.direction * forward * self.move_speed * dt

        if strafe != 0:
            right = self.direction.rotate(90)
            new_xy += right * strafe * self.move_speed * dt

        if state is not None:
            new_xy = state.get_closest_unobstructed_pos(new_xy)

        self.xy = new_xy

    def turn(self, direction, dt):
        self.direction.rotate_ip(direction * self.turn_speed * dt)

    def jump(self):
        if self.z == 0 and self._z_vel == 0:
            self._z_vel = 8

    def update(self, dt):
        if self.z > 0 or self._z_vel != 0:
            self._z_vel += self.grav * dt
            self.z += self._z_vel * dt
        if self.z <= 0:
            self.z = 0
            self._z_vel = 0


class GameWorld:

    def __init__(self, grid_dims, cell_size, bg_color=(0, 0, 0)):
        self.grid = []
        for _ in range(grid_dims[0]):
            self.grid.append([None] * grid_dims[1])
        self.cell_size = cell_size
        self.bg_color = bg_color

    def randomize(self, chance=0.2, n_colors=5):
        colors = []
        for _ in range(n_colors):
            colors.append((random.randint(50, 255),
                           random.randint(50, 255),
                           random.randint(50, 255)))
        for xy in self.all_cells():
            if random.random() < chance:
                color = random.choice(colors)
                self.set_cell(xy, color)
        self.fill_border(colors[0])
        return self

    def fill_border(self, color):
        W, H = self.get_dims()
        for i in range(W):
            self.set_cell((i, 0), color)
            self.set_cell((i, H - 1), color)
        for i in range(H):
            self.set_cell((0, i), color)
            self.set_cell((W - 1, i), color)

    def set_cell(self, xy, color):
        if self.is_valid(xy):
            self.grid[xy[0]][xy[1]] = color

    def is_valid(self, xy):
        return 0 <= xy[0] < self.get_dims()[0] and 0 <= xy[1] < self.get_dims()[1]

    def get_cell(self, xy):
        if self.is_valid(xy):
            return self.grid[xy[0]][xy[1]]
        else:
            return None

    def get_cell_coords_at(self, x, y):
        return (int(x / self.cell_size), int(y / self.cell_size))

    def get_cell_value_at(self, x, y):
        coords = self.get_cell_coords_at(x, y)
        return self.get_cell(coords)

    def all_cells(self, in_rect=None):
        dims = self.get_dims()
        x_min = 0 if in_rect is None else max(0, int(in_rect[0] / self.cell_size))
        y_min = 0 if in_rect is None else max(0, int(in_rect[1] / self.cell_size))
        x_max = dims[0] if in_rect is None else min(dims[0], int((in_rect[0] + in_rect[2]) / self.cell_size) + 1)
        y_max = dims[1] if in_rect is None else min(dims[1], int((in_rect[1] + in_rect[3]) / self.cell_size) + 1)
        for x in range(x_min, x_max):
            for y in range(y_min, y_max):
                yield (x, y)

    def get_dims(self):
        if len(self.grid) == 0:
            return (0, 0)
        else:
            return (len(self.grid), len(self.grid[0]))

    def get_size(self):
        dims = self.get_dims()
        return (dims[0] * self.cell_size, dims[1] * self.cell_size)

    def get_width(self):
        return self.get_size()[0]

    def get_height(self):
        return self.get_size()[1]


class RayState:
    """The state of a single ray."""
    def __init__(self, idx, start, end, ray, color):
        self.idx = idx
        self.start = start
        self.end = end
        self.ray = ray
        self.color = color

    def dist(self):
        if self.end is None:
            return float('inf')
        else:
            return (self.end - self.start).length()

    def __repr__(self):
        return "RayState(start={}, end={}, color={})".format(self.start, self.end, self.color)


class GameState:

    def __init__(self, player: Player, world: GameWorld, ents=()):
        self.player = player
        self.world = world
        self.entities = []
        self.game_over = False
        self.total_stars = 0

        self.ray_states = []
        for e in ents:
            self.add_entity(e)

        self.ellapsed_time = 0

    def add_entity(self, entity):
        self.entities.append(entity)
        if isinstance(entity, Pickup) and not entity.is_empty():
            self.total_stars += 1

    def remove_entity(self, entity):
        self.entities.remove(entity)

    def n_stars_remaining(self):
        return len([e for e in self.entities if isinstance(e, Pickup) and not e.is_empty()])

    def kill_player(self, killed_by):
        print("Player was killed by", killed_by.name)
        self.game_over = True

    def is_game_over(self):
        return self.game_over or self.n_stars_remaining() == 0

    def is_win(self):
        return self.n_stars_remaining() == 0

    def update_ray_states(self):
        self.ray_states.clear()
        i = 0
        for ray in self.player.get_rays():
            self.ray_states.append(self.cast_ray(i, self.player.xy, ray, self.player.max_depth))
            i += 1

    def has_line_of_sight(self, start_xy, end_xy):
        ray = (end_xy - start_xy)
        ray.scale_to_length(1)
        dist = start_xy.distance_to(end_xy)
        return self.cast_ray(-1, start_xy, ray, dist).end is None

    def get_closest_unobstructed_pos(self, xy, buffer_zone=4) -> Vector2:
        cell_xy = self.world.get_cell_coords_at(xy[0], xy[1])
        res_xy = xy
        if self.world.get_cell(cell_xy) is not None:
            dirs = [Vector2(0, 1), Vector2(-1, 0), Vector2(0, -1), Vector2(1, 0),
                    Vector2(1, 1), Vector2(-1, 1), Vector2(1, -1), Vector2(-1, -1)]
            rays = [self.cast_ray(-1, xy, d, self.world.cell_size * 2.5, antiray=True, ignore_cells=[cell_xy]) for d in dirs]
            rays.sort(key=lambda r: 1000 if r.end is None else r.dist())
            if rays[0].end is not None:
                new_pos = rays[0].end
                pushout_dir = rays[0].ray
                pushout_dir.scale_to_length(buffer_zone / 2)
                res_xy = new_pos + pushout_dir
            else:
                return xy  # failed

        if buffer_zone > 0:
            ortho_dists = self.ortho_distances_to_walls(res_xy, max_dist=buffer_zone)
            for adir in ortho_dists.keys():
                if ortho_dists[adir] <= buffer_zone:
                    vvv = GameState.dir_to_vect[adir]
                    res_xy += (-1*vvv) * (buffer_zone-ortho_dists[adir])  # push it out, away from the wall

        return res_xy

    dirs = [
        (0,1),
        (-1,0),
        (1,0),
        (0,-1)
    ]
    dir_to_vect = {
        (0,1):Vector2(0, 1),
        (-1,0):Vector2(-1, 0),
        (1,0):Vector2(1, 0),
        (0,-1):Vector2(0, -1),
    }
    def ortho_distances_to_walls(self, xy, max_dist=100):
        """
            dict in the form {
              (0,1): 8.789789,
              ...
            }
        """
        assoc_dir_dist = dict()
        for a_dir in GameState.dirs:
            assoc_dir_dist[a_dir] = self.cast_ray(-1, xy, GameState.dir_to_vect[a_dir], max_dist).dist()
        return assoc_dir_dist

    def cast_ray(self, idx, start_xy, ray, max_dist, antiray=False, ignore_cells=None) -> RayState:
        # yoinked from https://theshoemaker.de/2016/02/ray-casting-in-2d-grids/
        dirSignX = ray[0] > 0 and 1 or -1
        dirSignY = ray[1] > 0 and 1 or -1

        tileOffsetX = (ray[0] > 0 and 1 or 0)
        tileOffsetY = (ray[1] > 0 and 1 or 0)

        curX, curY = start_xy[0], start_xy[1]
        tileX, tileY = self.world.get_cell_coords_at(curX, curY)
        t = 0

        cell_size = self.world.cell_size

        maxX = start_xy[0] + ray[0] * max_dist
        maxY = start_xy[1] + ray[1] * max_dist

        if ray.length() > 0:
            while ((curX <= maxX if ray[0] >= 0 else curX >= maxX)
                   and (curY <= maxY if ray[1] >= 0 else curY >= maxY)):

                if ignore_cells is None or (tileX, tileY) not in ignore_cells:
                    color_at_cur_xy = self.world.get_cell((tileX, tileY))
                    if (color_at_cur_xy is not None) != antiray:
                        return RayState(idx, start_xy, Vector2(curX, curY), ray, color_at_cur_xy)

                dtX = float('inf') if ray[0] == 0 else ((tileX + tileOffsetX) * cell_size - curX) / ray[0]
                dtY = float('inf') if ray[1] == 0 else ((tileY + tileOffsetY) * cell_size - curY) / ray[1]

                if dtX < dtY:
                    t = t + dtX
                    tileX = tileX + dirSignX
                else:
                    t = t + dtY
                    tileY = tileY + dirSignY

                curX = start_xy[0] + ray[0] * t
                curY = start_xy[1] + ray[1] * t

        return RayState(idx, start_xy, None, ray, None)


def lerp(v1, v2, a):
    if isinstance(v1, float) or isinstance(v1, int):
        return v1 + a * (v2 - v1)
    else:
        return tuple(lerp(v1[i], v2[i], a) for i in range(len(v1)))


def bound(v, lower, upper):
    if isinstance(v, float) or isinstance(v, int):
        if v > upper:
            return upper
        elif v < lower:
            return lower
        else:
            return v
    else:
        return tuple(bound(v[i], lower, upper) for i in range(len(v)))


def round_tuple(v):
    return tuple(round(v[i]) for i in range(len(v)))


def lerp_color(c1, c2, a):
    return bound(round_tuple(lerp(c1, c2, a)), 0, 255)


class RayCastRenderer:

    def __init__(self):
        pass

    def render(self, screen, state: GameState):
        p_xy = state.player.xy

        cs = state.world.cell_size
        screen_size = screen.get_size()
        cam_offs = Vector2(-p_xy[0] + screen_size[0] // 2,
                           -p_xy[1] + screen_size[1] // 2)

        bg_color = lerp_color(state.world.bg_color, (255, 255, 255), 0.05)

        for r in state.ray_states:
            color = r.color if r.color is not None else bg_color
            if r.end is not None:
                color = lerp_color(color, bg_color, r.dist() / state.player.max_depth)
                pygame.draw.line(screen, color, r.start + cam_offs, r.end + cam_offs)
            else:
                pygame.draw.line(screen, color, r.start + cam_offs, r.start + r.ray * state.player.max_depth + cam_offs)

        camera_rect = [p_xy[0] - screen_size[0] // 2, p_xy[1] - screen_size[1] // 2, screen_size[0], screen_size[1]]

        for xy in state.world.all_cells(in_rect=camera_rect):
            color = state.world.get_cell(xy)
            if color is not None:
                r = [xy[0] * cs + cam_offs[0], xy[1] * cs + cam_offs[1], cs, cs]
                pygame.draw.rect(screen, color, r)

        for ent in state.entities:
            rect = ent.get_rect()
            rect = [rect[0] + cam_offs[0], rect[1] + cam_offs[1], rect[2], rect[3]]
            color = ent.get_color_2d()
            pygame.draw.rect(screen, color, rect, 1)


class RayCastRenderer3D(RayCastRenderer):

    def __init__(self):
        super().__init__()
        self.wall_height = 5
        self.eye_level = 2.7

    def render(self, screen, state: GameState):
        n_rays = len(state.ray_states)
        bg_color = lerp_color(state.world.bg_color, (255, 255, 255), 0.05)
        p_xy = state.player.xy
        p_dir = state.player.direction

        screen_size = screen.get_size()
        half_fovy = state.player.fov[1] / 2
        half_fovx = state.player.fov[0] / 2

        things_to_render = []

        for ent in state.entities:
            direction_to_ent = ent.xy - p_xy
            if 0 < direction_to_ent.length() <= state.player.max_depth:
                angle_to_ent = p_dir.angle_to(direction_to_ent)
                if angle_to_ent <= half_fovx:
                    # it's onscreen
                    things_to_render.append(ent)

        things_to_render.extend([r for r in state.ray_states if r.end is not None])
        sort_key = lambda r: r.dist() if isinstance(r, RayState) else r.xy.distance_to(p_xy)
        things_to_render.sort(key=sort_key, reverse=True)

        cur_eye_level = self.eye_level + state.player.z

        for r in things_to_render:
            if isinstance(r, RayState):
                i = r.idx
                color = lerp_color(r.color, bg_color, r.dist() / state.player.max_depth)
                theta_upper = math.degrees(math.atan2(self.wall_height - cur_eye_level, r.dist()))
                theta_lower = abs(math.degrees(math.atan2(cur_eye_level, r.dist())))
                rect_y1 = 0 if theta_upper >= half_fovy else screen_size[1] // 2 * (1 - theta_upper / half_fovy)
                rect_y2 = screen_size[1] if theta_lower >= half_fovy else screen_size[1] // 2 * (1 + theta_lower / half_fovy)
                rect_x1 = int(screen_size[0] * i / n_rays)
                rect_x2 = int(screen_size[0] * (i + 1) / n_rays)
                screen_rect = [rect_x1, int(rect_y1), rect_x2 - rect_x1 + 1, int(rect_y2 - rect_y1 + 1)]
                pygame.draw.rect(screen, color, screen_rect)
            elif isinstance(r, Entity):
                to_ent = r.xy - p_xy
                angle_from_left = p_dir.rotate(-half_fovx).angle_to(to_ent)
                theta_upper = math.degrees(math.atan2(r.height - cur_eye_level, to_ent.length()))
                theta_lower = abs(math.degrees(math.atan2(cur_eye_level, to_ent.length())))
                rect_y1 = 0 if theta_upper >= half_fovy else screen_size[1] // 2 * (1 - theta_upper / half_fovy)
                rect_y2 = screen_size[1] if theta_lower >= half_fovy else screen_size[1] // 2 * (1 + theta_lower / half_fovy)
                rect_height = rect_y2 - rect_y1 + 1
                rect_width = rect_height / r.height * r.width
                rect_cx = angle_from_left / (half_fovx * 2) * screen_size[0]
                screen_rect = [int(rect_cx - rect_width / 2), int(rect_y1), int(rect_width), int(rect_height)]

                # XXX pygame.transform.scale doesn't work in web mode~
                if r.image is not None and not kataen.runs_in_web():
                    dest_surf = pygame.Surface((screen_rect[2], screen_rect[3]))
                    dest_surf.set_colorkey(r.image.get_colorkey())
                    xformed_img = pygame.transform.scale(r.image, (screen_rect[2], screen_rect[3]), dest_surf)
                    screen.blit(xformed_img, (screen_rect[0], screen_rect[1]))
                else:
                    pygame.draw.rect(screen, r.get_color_2d(), screen_rect, 2)


def rect_contains(rect, pt):
    return rect[0] <= pt[0] < rect[0] + rect[2] and rect[1] <= pt[1] < rect[1] + rect[3]


class RayCasterGame(BaseGame):

    def __init__(self):
        super().__init__(True)  # fps tracking
        
        self.state = None
        self.renderer = RayCastRenderer3D()
        self.show_controls = True

        self._info_font = None
        self._runs_in_web_ctx = kataen.runs_in_web()

    def render_text(self, screen, text, size=12, pos=(0, 0), xanchor=0, color=(255, 255, 255), bg_color=None):
        if self._info_font is None or self._info_font.get_height() != size:
            self._info_font = pygame.font.Font(None, size)
        lines = text.split("\n")
        y = pos[1]
        for a_line in lines:
            surf = self._info_font.render(a_line, True, color, bg_color)
            screen.blit(surf, (int(pos[0] - xanchor * surf.get_width()), y))
            y += surf.get_height()

    def _build_initial_state(self):
        W, H = 64, 48
        CELL_SIZE = 16
        N_STARS = 4

        w = GameWorld((W, H), CELL_SIZE).randomize()
        xy = Vector2(w.get_width() / 2, w.get_height() / 2)
        p = Player(xy, fov=(60, 45), n_rays=60, move_speed=50, turn_speed=160, sight=200)

        ents = [
            Enemy("Skulker", Art.ENEMIES[0], Vector2(W * 0.25 * CELL_SIZE, H * 0.25 * CELL_SIZE), move_speed=25, aggro_cooldown=15),
            Enemy("Observer", Art.ENEMIES[1], Vector2(W * 0.75 * CELL_SIZE, H * 0.25 * CELL_SIZE), move_speed=30, sight=200),
            Enemy("Remorse", Art.ENEMIES[2], Vector2(W * 0.75 * CELL_SIZE, H * 0.75 * CELL_SIZE), move_speed=40, sight=90, aggro_cooldown=10),
            Enemy("Conjurer", Art.ENEMIES[3], Vector2(W * 0.25 * CELL_SIZE, H * 0.75 * CELL_SIZE), move_speed=20, turn_speed=90, sight=150)
        ]
        for i in range(N_STARS):
            pos = Vector2(CELL_SIZE * (0.5 + random.randint(0, W - 1)),
                          CELL_SIZE * (0.5 + random.randint(0, H - 1)))
            ents.append(Pickup("Pickup {}".format(i+1), Art.PICKUPS[i % 4], pos))

        # clear cells adjacent to player and entities
        for e in ents + [p]:
            cell = w.get_cell_coords_at(e.xy[0], e.xy[1])
            for x in range(cell[0] - 1, cell[0] + 2):
                for y in range(cell[1] - 1, cell[1] + 2):
                    w.set_cell((x, y), None)

        return GameState(p, w, ents=ents)

    def get_mode(self):
        return 'SUPER_RETRO'

    def pre_update(self):
        Art.load_from_disk()

    def update(self, events, dt):
        if self.state is None:
            self.state = self._build_initial_state()
        
        if not self._runs_in_web_ctx:  # calling set_caption is not always useful
            if self.get_tick() % 20 == 0:
                dims = self.get_screen_size()
                cap = "Raycaster (DIMS={}, FPS={:.1f})".format(dims, self.get_fps())
                pygame.display.set_caption(cap)
        
        pressed = pygame.key.get_pressed()

        for e in events:
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_r:
                    print("Resetting! [pressed R]")
                    self.state = self._build_initial_state()
                elif e.key == pygame.K_f:
                    if isinstance(self.renderer, RayCastRenderer3D):
                        print("Switching render mode to 2D. [pressed F]")
                        self.renderer = RayCastRenderer()
                    else:
                        print("Switching render mode to 3D. [pressed F]")
                        self.renderer = RayCastRenderer3D()
                elif e.key == pygame.K_c:
                    self.show_controls = not self.show_controls
                elif e.key == pygame.K_SPACE:
                    if not self.state.is_game_over():
                        self.state.player.jump()
                elif e.key == pygame.K_EQUALS or e.key == pygame.K_MINUS:  # TODO these events aren't detected on web~
                    cur_rays = self.state.player.n_rays
                    ray_change = 5 if not pressed[pygame.K_LSHIFT] else 10
                    if e.key == pygame.K_MINUS:
                        ray_change *= -1
                    self.state.player.n_rays = bound(cur_rays + ray_change, 5, self.get_screen_size()[0])

            elif e.type == pygame.MOUSEBUTTONDOWN:
                if e.button == 4 or e.button == 5:  # TODO these events aren't detected on web either~
                    cur_rays = self.state.player.n_rays
                    ray_change = 1 if not pressed[pygame.K_LSHIFT] else 5
                    # scroll up to increase, scroll down to decrease
                    if e.button == 5:
                        ray_change *= -1
                    self.state.player.n_rays = bound(cur_rays + ray_change, 3, self.get_screen_size()[0])

        turn = 0
        if pressed[pygame.K_q] or pressed[pygame.K_LEFT]:
            turn -= 1
        if pressed[pygame.K_e] or pressed[pygame.K_RIGHT]:
            turn += 1

        forward = 0
        strafe = 0
        if not self.state.is_game_over():
            if pressed[pygame.K_w] or pressed[pygame.K_UP]:
                forward += 1
            if pressed[pygame.K_s] or pressed[pygame.K_DOWN]:
                forward -= 1

            if pressed[pygame.K_a]:
                strafe -= 1
            if pressed[pygame.K_d]:
                strafe += 1

        self.state.player.turn(turn, dt)
        self.state.player.move(forward, strafe, dt, state=self.state)
        self.state.player.update(dt)

        for ent in list(self.state.entities):
            ent.update(self.state, dt)
            if not self.state.is_game_over() and self.state.player.xy.distance_to(ent.xy) <= ent.radius:
                ent.on_collide_with_player(self.state)

        self.state.update_ray_states()

        if not self.state.is_game_over():
            self.state.ellapsed_time += dt

    def render(self, screen):
        screen.fill((0, 0, 0))
        self.renderer.render(screen, self.state)

        fps_text = "FPS {:.1f}".format(self.get_fps())
        if self.show_controls:
            rays_text = "RAYS: {} [+/-] to change".format(self.state.player.n_rays)
            movekeys = "[WASDQE] or [arrows] to move"
            r_to_reset = "[R] to reset"
            f_to_swap_modes = "[F] to change to " + ("2D" if isinstance(self.renderer, RayCastRenderer3D) else "3D")
            c_to_hide_instructions = "[C] to hide controls"
            full_text = "\n".join([fps_text, movekeys, rays_text, r_to_reset, f_to_swap_modes, c_to_hide_instructions])
        else:
            c_to_show_instructions = "[C] to show controls"
            full_text = "\n".join([fps_text, c_to_show_instructions])
        self.render_text(screen, full_text, bg_color=(0, 0, 0), size=16)

        total_stars = self.state.total_stars
        collected = total_stars - self.state.n_stars_remaining()
        info_text = "Collect all Stars ({}/{})".format(collected, total_stars)
        self.render_text(screen, info_text, pos=(screen.get_size()[0], 0), xanchor=1.0, bg_color=(0, 0, 0), size=16)

        if self.state.is_game_over():
            if self.state.is_win():
                mins = int(self.state.ellapsed_time) // 60
                secs = self.state.ellapsed_time % 60
                text = "You win!\n{}:{:.1f}\nPress [R] to restart".format(mins, secs)
            else:
                text = "You lose!\nPress [R] to restart"
            self.render_text(screen, text, pos=(screen.get_size()[0] // 2, screen.get_size()[1] // 2),
                             xanchor=0.5, bg_color=(0, 0, 0), size=16)


############## raycaster.py ##############

############## entities.py ##############


class Entity:

    def __init__(self, name, image, xy, width, height, radius=10):
        self.name = name
        self.image = image
        self.xy = xy
        self.width = width
        self.height = height
        self.radius = radius  # for collisions with player

    def get_rect(self):
        return [self.xy[0] - self.width // 2,
                self.xy[1] - self.width // 2,
                self.width, self.width]

    def get_color_2d(self):
        return (255, 255, 255)

    def get_image(self):
        return self.image

    def update(self, state, dt):
        pass

    def on_collide_with_player(self, state):
        pass


class Enemy(Entity):

    def __init__(self, name, image, xy, turn_speed=180, move_speed=25, aggro_cooldown=5, sight=120):
        super().__init__(name, image, xy, 4, 8, 3)
        self.vel = Vector2(0, 1).rotate(360 * random.random())
        self.turn_speed = turn_speed
        self.move_speed = move_speed

        self.is_aggro = False
        self.aggro_cooldown = 0
        self.max_aggro_cooldown = aggro_cooldown  # seconds
        self.sight_radius = sight

    def get_image(self):
        return self.image

    def get_color_2d(self):
        return (255, 0, 0)

    def update(self, state, dt):
        player_xy = state.player.xy
        if not state.is_game_over() and (self.xy.distance_to(player_xy) < self.sight_radius
                                         and state.has_line_of_sight(self.xy, player_xy)):
            self.aggro_cooldown = self.max_aggro_cooldown
            if not self.is_aggro:
                print("{} became aggressive!".format(self.name))
                self.is_aggro = True

        if self.is_aggro and (self.aggro_cooldown < 0 or state.is_game_over()):
            print("{} became passive!".format(self.name))
            self.is_aggro = False

        if self.is_aggro:
            self.vel = player_xy - self.xy
            self.vel.scale_to_length(1)
        else:
            # just turn randomly
            self.vel = self.vel.rotate(2 * (random.random() - 0.5) * self.turn_speed * dt)

        ms = self.move_speed if self.is_aggro else 0.666 * self.move_speed
        new_pos = self.xy + self.vel * ms * dt

        unwalled_new_pos = state.get_closest_unobstructed_pos(new_pos)
        if not self.is_aggro and unwalled_new_pos != new_pos:
            # it bonked a wall, turn
            self.vel = self.vel.rotate(360 * random.random())

        self.xy = unwalled_new_pos
        self.aggro_cooldown -= dt

    def on_collide_with_player(self, state):
        state.kill_player(self)
        pass


class Pickup(Entity):

    def __init__(self, name, image, xy):
        super().__init__(name, image, xy, 4, 8, 10)

    def get_color_2d(self):
        return (0, 255, 255)

    def on_collide_with_player(self, state):
        state.remove_entity(self)
        state.add_entity(EmptyPickup(self.xy))

    def is_empty(self):
        return False


class EmptyPickup(Pickup):

    def __init__(self, xy):
        super().__init__("Empty Pickup", Art.PICKUPS[-1], xy)

    def get_color_2d(self):
        return (0, 150, 255)

    def on_collide_with_player(self, state):
        pass

    def is_empty(self):
        return True

############## entities.py ##############

############## main.py ##############


def run_game():
    """Entry point for packaged web runs"""
    g = RayCasterGame()
    g.start()


if __name__ == '__main__':
    """Entry point for offline runs"""
    run_game()

############## main.py ##############
