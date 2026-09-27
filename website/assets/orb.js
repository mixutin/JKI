(() => {
  const canvas = document.getElementById("jake-orb");
  const stage = document.getElementById("orb-stage");
  if (!canvas || !stage) return;
  const buttons = [...document.querySelectorAll(".orb-state")];
  const label = document.getElementById("orb-state-label");
  const pause = document.getElementById("pause-motion");
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  let paused = motion.matches;
  let visible = true;
  let targetMode = 0;
  let mode = 0;
  let time = 7;
  let frame = 0;
  let last = 0;
  let gl;
  let render = () => {};
  const pointer = { x: 0, y: 0, tx: 0, ty: 0 };
  function updatePause() {
    pause.textContent = paused ? "Play animation" : "Pause animation";
    pause.setAttribute("aria-pressed", String(paused));
    render();
  }
  buttons.forEach((button, index) =>
    button.addEventListener("click", () => {
      targetMode = index;
      stage.dataset.state = button.dataset.state;
      label.textContent =
        "0" + (index + 1) + " / " + button.dataset.state.toUpperCase();
      buttons.forEach((b) => {
        b.classList.toggle("active", b === button);
        b.setAttribute("aria-pressed", String(b === button));
      });
      if (paused) mode = targetMode;
      render();
    }),
  );
  pause.addEventListener("click", () => {
    paused = !paused;
    updatePause();
  });
  motion.addEventListener("change", () => {
    paused = motion.matches;
    updatePause();
  });
  updatePause();
  try {
    gl = canvas.getContext("webgl", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: false,
      powerPreference: "low-power",
    });
    if (!gl) {
      pause.hidden = true;
      return;
    }
    function shader(type, source) {
      const s = gl.createShader(type);
      gl.shaderSource(s, source);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(s));
      return s;
    }
    const program = gl.createProgram();
    gl.attachShader(
      program,
      shader(
        gl.VERTEX_SHADER,
        "attribute vec2 aPosition; void main(){gl_Position=vec4(aPosition,0.,1.);}",
      ),
    );
    gl.attachShader(
      program,
      shader(
        gl.FRAGMENT_SHADER,
        document.getElementById("orb-fragment").textContent,
      ),
    );
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS))
      throw new Error("Orb program failed to link");
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW,
    );
    const position = gl.getAttribLocation(program, "aPosition");
    gl.enableVertexAttribArray(position);
    gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
    const resolution = gl.getUniformLocation(program, "uResolution");
    const clock = gl.getUniformLocation(program, "uTime");
    const cursor = gl.getUniformLocation(program, "uPointer");
    const state = gl.getUniformLocation(program, "uMode");
    function draw() {
      const box = canvas.getBoundingClientRect();
      const scale = Math.min(devicePixelRatio || 1, 1.3);
      const width = Math.max(1, Math.round(box.width * scale));
      const height = Math.max(1, Math.round(box.height * scale));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        gl.viewport(0, 0, width, height);
      }
      gl.uniform2f(resolution, width, height);
      gl.uniform1f(clock, time);
      gl.uniform2f(cursor, pointer.x, pointer.y);
      gl.uniform1f(state, mode);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    }
    function tick(now) {
      frame = 0;
      if (!visible || document.hidden) {
        last = 0;
        return;
      }
      if (!paused && now - last >= 32) {
        time += last ? Math.min((now - last) / 1000, 0.06) : 0.016;
        last = now;
        pointer.x += (pointer.tx - pointer.x) * 0.07;
        pointer.y += (pointer.ty - pointer.y) * 0.07;
        mode += (targetMode - mode) * 0.06;
        draw();
      }
      if (!paused) frame = requestAnimationFrame(tick);
    }
    render = () => {
      draw();
      if (!frame && !paused && visible && !document.hidden)
        frame = requestAnimationFrame(tick);
    };
    new ResizeObserver(render).observe(canvas);
    new IntersectionObserver(
      (entries) => {
        visible = entries[0].isIntersecting;
        if (visible) render();
      },
      { threshold: 0.05 },
    ).observe(canvas);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) render();
    });
    stage.addEventListener("pointermove", (event) => {
      if (paused || event.pointerType === "touch") return;
      const box = stage.getBoundingClientRect();
      pointer.tx = ((event.clientX - box.left) / box.width) * 2 - 1;
      pointer.ty = 1 - ((event.clientY - box.top) / box.height) * 2;
    });
    stage.addEventListener("pointerleave", () => {
      pointer.tx = 0;
      pointer.ty = 0;
    });
    canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      cancelAnimationFrame(frame);
      frame = 0;
      paused = true;
      stage.classList.remove("webgl-ready");
      pause.hidden = true;
    });
    render();
    stage.classList.add("webgl-ready");
  } catch (error) {
    stage.classList.remove("webgl-ready");
    pause.hidden = true;
    console.warn("Jake is using the static orb fallback.", error.message);
  }
})();
